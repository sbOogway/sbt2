import contextlib
import logging
import multiprocessing
import time
from collections import deque
from collections.abc import Sequence
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess

from sbt2.core.run.batching.errors import OutOfMemoryError, RunFailedError
from sbt2.core.run.batching.memory import formatted_size
from sbt2.core.run.batching.setup import BatchProgress, BatchSetup
from sbt2.core.run.child import Order, run_child, send

logger = logging.getLogger(__name__)

_FORKSERVER = multiprocessing.get_context("forkserver")
_PRELOADED = ["sbt2.core.run.child"]

_POLL_SECONDS = 0.05
_GRACE_SECONDS = 5


class Children:
    """The running children of a batch, at most ``concurrency`` at a time."""

    def __init__(self, setup: BatchSetup, progress: BatchProgress) -> None:
        self._launcher = setup.launcher
        self._store = setup.store
        self._memory = setup.memory
        self._progress = progress
        self._running: dict[str, tuple[BaseProcess, Order]] = {}

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
        child, pipe = _spawn()
        self._running[order.run_id] = (child, order)
        with pipe:
            self._launcher.cap(order.run_id, _pid(child), self._memory.per_run)
            logger.info("started run %s", order.run_id)
            # a child that exited before reading is reaped by its exit code
            with contextlib.suppress(BrokenPipeError):
                send(order, pipe)

    def _reap(self) -> bool:
        exited = [
            (run_id, code)
            for run_id, (child, _) in self._running.items()
            if (code := child.exitcode) is not None
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
            cap = formatted_size(self._memory.per_run)
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
            child.join(_GRACE_SECONDS)
            if child.exitcode is None:
                child.kill()
                child.join()
        self._running.clear()


def _spawn() -> tuple[BaseProcess, Connection]:
    """Fork a child from the forkserver, which starts at the first child with the
    run modules loaded; the child waits on the returned pipe for its order."""
    _FORKSERVER.set_forkserver_preload(_PRELOADED)
    reader, writer = _FORKSERVER.Pipe(duplex=False)
    child = _FORKSERVER.Process(target=run_child, args=(reader,))
    child.start()
    reader.close()
    return child, writer


def _pid(child: BaseProcess) -> int:
    if child.pid is None:
        raise ValueError("the child was never started")
    return child.pid
