import logging
import subprocess
import sys
import time
from collections import deque
from collections.abc import Sequence

from sbt2.core.run.batching.errors import OutOfMemoryError, RunFailedError
from sbt2.core.run.batching.memory import formatted_size
from sbt2.core.run.batching.setup import BatchProgress, BatchSetup
from sbt2.core.run.child import Order, send

logger = logging.getLogger(__name__)

_POLL_SECONDS = 0.05
_GRACE_SECONDS = 5


class Children:
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
        child = _spawn()
        self._running[order.run_id] = (child, order)
        if child.stdin is None:
            raise ValueError(f"run {order.run_id} was started without a stdin pipe")
        self._launcher.cap(order.run_id, child.pid, self._memory.per_run)
        logger.info("started run %s", order.run_id)
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
            try:
                child.wait(_GRACE_SECONDS)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        self._running.clear()


def _spawn() -> subprocess.Popen[bytes]:
    """Start a child, which waits on stdin for its order."""
    return subprocess.Popen(
        [sys.executable, "-m", "sbt2.core.run"], stdin=subprocess.PIPE
    )
