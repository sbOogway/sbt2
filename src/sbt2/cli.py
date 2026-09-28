import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from nautilus_trader.common import LogLevel
from rich.console import Console
from rich.filesize import decimal
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
)

from sbt2 import data, sources, spec
from sbt2.results import ParquetResultStore, Provenance
from sbt2.run import RunSettings, execute

DATA = Path("data")
SOURCES = Path("config/sources.toml")
DAY = ["%Y-%m-%d"]
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
logger = logging.getLogger("sbt2")


class Level(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@app.callback()
def main(
    context: typer.Context,
    log_level: Annotated[
        Level, typer.Option(help="For sbt2 and nautilus.")
    ] = Level.INFO,
    log_file: Annotated[Path | None, typer.Option(help="Also log here.")] = None,
) -> None:
    """Backtesting on nautilus_trader."""
    _configure_logging(log_level, log_file)
    context.obj = log_level


@app.command()
def run(
    context: typer.Context,
    spec_file: Annotated[Path, typer.Argument(help="The run spec, a TOML file.")],
    data: Annotated[Path, typer.Option(help="Holds catalog/ and results/.")] = DATA,
) -> None:
    """Run the backtest a spec file describes and store its result."""
    try:
        _run(spec_file, data, LogLevel.from_str(context.obj))
    except Exception:
        logger.exception("run of %s failed", spec_file)
        raise typer.Exit(1) from None


def _run(spec_file: Path, data: Path, log_level: LogLevel) -> None:
    resolved = spec.load(spec_file)
    store = ParquetResultStore(data / "results")
    sink = store.new_run(resolved, Provenance.of_repo(Path.cwd()))
    execute(resolved, sink, RunSettings(data / "catalog", log_level=log_level))
    logger.info("stored run %s in %s", sink.run_id, data / "results")


@app.command()
def download(
    source: Annotated[str, typer.Option(help="A source in config/sources.toml.")],
    symbol: Annotated[list[str], typer.Option(help="Repeat for several.")],
    start: Annotated[datetime, typer.Option(formats=DAY, help="The first UTC day.")],
    end: Annotated[
        datetime, typer.Option(formats=DAY, help="The last UTC day, included.")
    ],
    data_type: Annotated[
        list[str] | None,
        typer.Option(
            "--type",
            help="A nautilus data type the source serves; repeat for several. "
            "Default: all of them.",
        ),
    ] = None,
    data_root: Annotated[
        Path, typer.Option("--data", help="Raw files go to PATH/raw.")
    ] = DATA,
    concurrency: Annotated[int, typer.Option(min=1)] = 8,
    retries: Annotated[int, typer.Option(min=0, help="Per file.")] = 5,
) -> None:
    """Fetch a source's raw files for a range of days, and today's instruments."""
    options = data.DownloadOptions(data_root / "raw", concurrency, retries)
    try:
        request = data.DownloadRequest(
            tuple(symbol), start.date(), end.date(), tuple(data_type or ())
        )
        report = _download(source, request, options)
    except Exception:
        logger.exception("download from %s failed", source)
        raise typer.Exit(1) from None
    _log_summary(report)
    if report.having(data.Outcome.FAILED):
        raise typer.Exit(1)


def _download(
    name: str, request: data.DownloadRequest, options: data.DownloadOptions
) -> data.DownloadReport:
    adapter = sources.source(name, SOURCES)
    with _download_bar() as bar:
        return data.download(adapter, request, replace(options, progress=bar))


def _log_summary(report: data.DownloadReport) -> None:
    for each in report.having(data.Outcome.MISSING):
        logger.warning("missing at the source: %s", _described(each.item))
    for each in report.having(data.Outcome.FAILED):
        logger.error("failed: %s: %s", _described(each.item), each.reason)
    counts = (f"{len(report.having(each))} {each}" for each in data.Outcome)
    logger.info("files: %s", ", ".join(counts))


def _described(item: data.Item) -> str:
    return f"{item.symbol} {item.data} {item.day.isoformat()}"


class _DownloadBar:
    """Files done out of those planned, and the bytes received so far."""

    def __init__(self, progress: Progress) -> None:
        self._progress = progress
        self._task = progress.add_task("download", total=None, size="")
        self._size = 0

    def planned(self, files: int) -> None:
        self._progress.update(self._task, total=files)

    def received(self, size: int) -> None:
        self._size += size
        self._progress.update(self._task, size=decimal(self._size))

    def finished(self, result: data.FileResult) -> None:
        self._progress.advance(self._task)


@contextmanager
def _download_bar() -> Iterator[_DownloadBar]:
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.fields[size]}"),
        TimeElapsedColumn(),
        console=Console(stderr=True),
    ) as progress:
        yield _DownloadBar(progress)


def _configure_logging(level: Level, log_file: Path | None) -> None:
    """Configures the ``sbt2`` logger only, so it never clobbers the host's."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file))
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for handler in handlers:
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(level)
