from collections.abc import Generator, Sequence
from contextlib import contextmanager

from rich.console import Console
from rich.filesize import decimal
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)


class _Bar:
    """Items done out of those planned."""

    def __init__(self, progress: Progress, task: TaskID) -> None:
        self._progress = progress
        self._task = task

    def planned(self, count: int) -> None:
        self._progress.update(self._task, total=count)

    def finished(self, _result: object, /) -> None:
        self._progress.advance(self._task)


class _DownloadBar(_Bar):
    """Files done out of those planned, and the bytes received so far."""

    def __init__(self, progress: Progress, task: TaskID) -> None:
        super().__init__(progress, task)
        self._size = 0

    def received(self, size: int) -> None:
        self._size += size
        self._progress.update(self._task, size=decimal(self._size))


class _RunsBar:
    """Runs finished out of those planned."""

    def __init__(self, progress: Progress, task: TaskID) -> None:
        self._progress = progress
        self._task = task

    def planned(self, run_ids: Sequence[str]) -> None:
        self._progress.update(self._task, total=len(run_ids))

    def started(self, _run_id: str, /) -> None:
        pass

    def finished(self, _run_id: str, /) -> None:
        self._progress.advance(self._task)


@contextmanager
def bar(description: str) -> Generator[_Bar]:
    with _progress() as progress:
        yield _Bar(progress, progress.add_task(description, total=None))


@contextmanager
def runs_bar() -> Generator[_RunsBar]:
    with _progress() as progress:
        yield _RunsBar(progress, progress.add_task("runs", total=None))


@contextmanager
def download_bar() -> Generator[_DownloadBar]:
    with _progress(TextColumn("{task.fields[size]}")) as progress:
        task = progress.add_task("download", total=None, size="")
        yield _DownloadBar(progress, task)


@contextmanager
def _progress(*extra: TextColumn) -> Generator[Progress]:
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        *extra,
        TimeElapsedColumn(),
        console=Console(stderr=True),
    ) as progress:
        yield progress
