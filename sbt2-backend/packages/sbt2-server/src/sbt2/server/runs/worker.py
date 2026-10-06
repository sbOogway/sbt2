"""A job's own process, which alone imports the strategy a client uploaded.

``python -m sbt2.server.runs.worker FD`` reads its job request from the channel
on file descriptor ``FD``, checks the job's specs, reports the runs it planned
and waits for ``go``; then it runs them as a batch, reporting each run's
progress. SIGTERM stops it, and the batch's children with it; so does the
server closing the channel.
"""

import logging
import os
import signal
import socket
import sys
import tempfile
import threading
from collections.abc import Sequence
from pathlib import Path
from types import FrameType

from nautilus_trader.common import LogLevel

from sbt2 import data
from sbt2.core import spec
from sbt2.core.config import Root
from sbt2.core.run import (
    BatchSetup,
    DuplicateStudyRunError,
    Launch,
    PreflightError,
    RunFailedError,
    StudyCodeError,
    StudyContextError,
    StudyError,
    Uncapped,
    batch,
)
from sbt2.server.runs.wire import (
    GO,
    Conflict,
    ConflictKind,
    Crashed,
    Done,
    Event,
    Failed,
    Finished,
    JobRequest,
    Planned,
    Rejected,
    Rejection,
    Started,
    encode,
)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
TERMINATED = 143

logger = logging.getLogger("sbt2.server.worker")

_INVALID = (
    spec.SpecError,
    PreflightError,
    StudyError,
    data.UnknownSourceError,
    data.UnsupportedDataTypeError,
    ImportError,
    SyntaxError,
    AttributeError,
    TypeError,
    ValueError,
    LookupError,
)


class Terminated(BaseException):
    """SIGTERM, raised where the job process is, so that its ``finally`` runs."""


class _Channel:
    def __init__(self, fd: int) -> None:
        os.set_inheritable(fd, False)
        connection = socket.socket(fileno=fd)
        self._reader = connection.makefile("r", encoding="utf-8")
        self._writer = connection.makefile("w", encoding="utf-8")
        self._go = threading.Event()

    def request(self) -> JobRequest:
        return JobRequest.from_line(self._reader.readline())

    def listen(self) -> None:
        threading.Thread(target=self._listen, daemon=True).start()

    def send(self, event: Event) -> None:
        self._writer.write(encode(event) + "\n")
        self._writer.flush()

    def wait_for_go(self) -> None:
        self._go.wait()

    def _listen(self) -> None:
        for line in self._reader:
            if line.strip() == GO:
                self._go.set()
        os.kill(os.getpid(), signal.SIGTERM)


class _Progress:
    def __init__(self, channel: _Channel) -> None:
        self._channel = channel
        self.planned_sent = False

    def planned(self, run_ids: Sequence[str], /) -> None:
        self._channel.send(Planned(tuple(run_ids)))
        self.planned_sent = True
        self._channel.wait_for_go()

    def started(self, run_id: str, /) -> None:
        self._channel.send(Started(run_id))

    def finished(self, run_id: str, /) -> None:
        self._channel.send(Finished(run_id))


def main() -> None:
    channel = _Channel(int(sys.argv[1]))
    request = channel.request()
    channel.listen()
    signal.signal(signal.SIGTERM, _terminate)
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    try:
        code = _run(request, channel)
    except Terminated:
        code = TERMINATED
    sys.exit(code)


def _terminate(_signal: int, _frame: FrameType | None) -> None:
    # a second SIGTERM must not interrupt the cleanup the first one started
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise Terminated


def _run(request: JobRequest, channel: _Channel) -> int:
    with tempfile.TemporaryDirectory(prefix="sbt2-strategy-") as folder:
        Path(folder, f"{request.module_name}.py").write_text(request.module_source)
        sys.path.insert(0, folder)
        progress = _Progress(channel)
        try:
            _batch(request, progress)
        except RunFailedError as error:
            channel.send(Failed(error.run_id, error.reason))
            return 1
        except Exception as error:
            logger.exception("the job failed")
            channel.send(_failure(error, progress))
            return 1
    channel.send(Done())
    return 0


def _batch(request: JobRequest, progress: _Progress) -> None:
    runs = spec.load_table(request.spec, Path(request.venues))
    setup = BatchSetup.at(
        Root(Path(request.data_root)), Launch(Uncapped()), LogLevel.INFO
    )
    batch(runs, setup, progress)


def _failure(error: Exception, progress: _Progress) -> Event:
    if progress.planned_sent:
        return Crashed(f"{type(error).__name__}: {error}")
    return _rejection(error)


def _conflict(error: Exception) -> Conflict | None:
    match error:
        case StudyContextError(keys=keys):
            return Conflict(ConflictKind.CONTEXT, context_keys=keys)
        case StudyCodeError():
            return Conflict(ConflictKind.CODE)
        case DuplicateStudyRunError(run_id=run_id):
            return Conflict(ConflictKind.DUPLICATE_RUN, run_id=run_id)
        case _:
            return None


def _rejection(error: Exception) -> Rejected:
    if isinstance(error, spec.UnknownVenueProfileError):
        return Rejected(Rejection.NOT_FOUND, _described(error))
    if isinstance(error, _INVALID):
        return Rejected(Rejection.INVALID, _described(error), _conflict(error))
    return Rejected(Rejection.INTERNAL, f"{type(error).__name__}: {error}")


def _described(error: Exception) -> str:
    return "; ".join([str(error), *getattr(error, "__notes__", [])])


if __name__ == "__main__":
    main()
