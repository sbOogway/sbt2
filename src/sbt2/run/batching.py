import logging
import os
import subprocess
import sys
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol

from sbt2.data import Gap, Source
from sbt2.results import ResultStore
from sbt2.run.child import Order, send
from sbt2.run.execute import RunSettings
from sbt2.run.preflight import DataFolders, preflight
from sbt2.spec import ResolvedRunSpec

logger = logging.getLogger(__name__)

GiB = 2**30
_CHILD = ("-m", "sbt2.run")
_POLL_SECONDS = 0.05
_GRACE_SECONDS = 5


class RunFailedError(RuntimeError):
    def __init__(self, run_id: str, folder: Path, reason: str) -> None:
        super().__init__(f"run {run_id} failed: {reason}; its folder is {folder}")
        self.run_id = run_id
        self.folder = folder


class OutOfMemoryError(RunFailedError):
    pass


class Launcher(Protocol):
    """Starts each child of a batch."""

    def check(self) -> None:
        """Raise if no child can be started here."""
        ...

    def start(
        self, run_id: str, command: Sequence[str], memory_max: int
    ) -> subprocess.Popen[bytes]:
        """Start ``command`` as the child running ``run_id``, its stdin a pipe,
        capped at ``memory_max`` bytes."""
        ...

    def out_of_memory(self, run_id: str) -> bool:
        """Whether the exited child running ``run_id`` was killed over its cap."""
        ...


class BatchProgress(Protocol):
    def planned(self, runs: int, /) -> None: ...

    def finished(self, run_id: str, /) -> None: ...


class _NoProgress:
    def planned(self, runs: int) -> None:
        pass

    def finished(self, run_id: str) -> None:
        pass


def _half_the_memory() -> int:
    return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // 2


@dataclass(frozen=True)
class Memory:
    """Bytes for a whole batch, and the cap of each of its runs.

    Without a budget, a batch takes half the machine's memory, and at least a run's.
    """

    budget: int | None = None
    per_run: int = 4 * GiB

    def __post_init__(self) -> None:
        if self.budget is not None and self.budget < self.per_run:
            raise ValueError(
                f"a memory budget of {_size(self.budget)} is below the "
                f"{_size(self.per_run)} each run gets"
            )

    @property
    def concurrency(self) -> int:
        budget = self.budget or max(_half_the_memory(), self.per_run)
        return budget // self.per_run


@dataclass(frozen=True)
class BatchSetup:
    """Each child reopens ``store`` from its locator and opens its own sink."""

    store: ResultStore
    sources: Callable[[str], Source]
    folders: DataFolders
    settings: RunSettings
    launcher: Launcher
    memory: Memory = field(default_factory=Memory)


def batch(
    specs: Sequence[ResolvedRunSpec],
    setup: BatchSetup,
    progress: BatchProgress | None = None,
) -> tuple[str, ...]:
    """Pre-flight every run, then execute each in a fresh process, all under one
    fresh batch id; returns their run_ids, in the order of ``specs``."""
    setup.launcher.check()
    known_gaps = [_preflight(each, setup) for each in specs]
    progress = progress or _NoProgress()
    progress.planned(len(specs))
    with TemporaryDirectory(prefix="sbt2-batch-") as errors:
        orders = _orders(zip(specs, known_gaps, strict=True), setup, Path(errors))
        _Children(setup, progress).run(orders)
    return tuple(each.run_id for each in orders)


def _preflight(spec: ResolvedRunSpec, setup: BatchSetup) -> tuple[Gap, ...]:
    return preflight(spec, setup.sources(spec.source), setup.folders)


def _orders(
    runs: Iterable[tuple[ResolvedRunSpec, tuple[Gap, ...]]],
    setup: BatchSetup,
    errors: Path,
) -> list[Order]:
    batch_id = str(uuid.uuid7())
    orders = []
    for spec, known_gaps in runs:
        run_id = str(uuid.uuid7())
        orders.append(
            Order(
                run_id,
                batch_id,
                spec,
                known_gaps,
                setup.store,
                setup.settings,
                errors / run_id,
            )
        )
    return orders


class _Children:
    """The running children of a batch, at most ``concurrency`` at a time."""

    def __init__(self, setup: BatchSetup, progress: BatchProgress) -> None:
        self._launcher = setup.launcher
        self._store = setup.store
        self._memory = setup.memory
        self._progress = progress
        self._running: dict[str, tuple[subprocess.Popen[bytes], Order]] = {}

    def run(self, orders: Sequence[Order]) -> None:
        try:
            self._run(deque(orders))
        finally:
            self._stop()

    def _run(self, pending: deque[Order]) -> None:
        while pending or self._running:
            while pending and len(self._running) < self._memory.concurrency:
                self._start(pending.popleft())
            if not self._reap():
                time.sleep(_POLL_SECONDS)

    def _start(self, order: Order) -> None:
        command = [sys.executable, *_CHILD]
        child = self._launcher.start(order.run_id, command, self._memory.per_run)
        self._running[order.run_id] = (child, order)
        logger.info("started run %s", order.run_id)
        if child.stdin is None:
            raise ValueError(
                f"the launcher started run {order.run_id} without a stdin pipe"
            )
        try:
            send(order, child.stdin)
            child.stdin.close()
        except BrokenPipeError:
            pass  # the child exited before reading; its exit code tells why

    def _reap(self) -> bool:
        exited = [
            (run_id, child.returncode)
            for run_id, (child, _) in self._running.items()
            if child.poll() is not None
        ]
        for run_id, code in exited:
            _, order = self._running.pop(run_id)
            if code != 0:
                raise self._failure(order, code)
            self._progress.finished(run_id)
        return bool(exited)

    def _failure(self, order: Order, code: int) -> RunFailedError:
        folder = self._store.folder(order.run_id)
        if self._launcher.out_of_memory(order.run_id):
            cap = _size(self._memory.per_run)
            reason = f"it ran out of memory over its {cap} cap"
            return OutOfMemoryError(order.run_id, folder, reason)
        if order.error_file.exists():
            reason = order.error_file.read_text()
        else:
            reason = f"its process exited with code {code}"
        return RunFailedError(order.run_id, folder, reason)

    def _stop(self) -> None:
        """Terminate the children still running, killing any that linger."""
        for child, _ in self._running.values():
            child.terminate()
        for child, _ in self._running.values():
            try:
                child.wait(_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        self._running.clear()


def _size(size: int) -> str:
    """Bytes in the largest binary unit that divides them, as systemd writes it."""
    for unit, power in (("T", 40), ("G", 30), ("M", 20), ("K", 10)):
        if size % 2**power == 0:
            return f"{size // 2**power}{unit}"
    return f"{size} bytes"
