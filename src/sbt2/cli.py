import json
import logging
import math
import re
import sys
from collections.abc import Hashable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import numpy as np
import pandas as pd
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

from sbt2 import data, spec
from sbt2.data import sources
from sbt2.results import MissingTableError, ParquetResultStore, ResultStore
from sbt2.run import (
    BatchSetup,
    DataFolders,
    Memory,
    RunSettings,
    SystemdScope,
    batch,
)

DATA = Path("data")
SOURCES = Path("config/sources.toml")
DAY = ["%Y-%m-%d"]
SIZE = re.compile(r"(\d+)([KMGT]?)")
SIZE_UNITS = {"": 0, "K": 10, "M": 20, "G": 30, "T": 40}
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
data_app = typer.Typer(no_args_is_help=True, help="Inspect the catalog.")
app.add_typer(data_app, name="data")
runs_app = typer.Typer(no_args_is_help=True, help="Query and manage stored runs.")
app.add_typer(runs_app, name="runs")
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


def _size(text: str) -> int:
    """Bytes, from a size in systemd's syntax such as ``512M`` or ``4G``."""
    match = SIZE.fullmatch(text)
    if match is None:
        raise ValueError(f"{text} is not a size such as 512M or 4G")
    number, unit = match.groups()
    return int(number) * 2 ** SIZE_UNITS[unit]


@app.command()
def run(
    context: typer.Context,
    spec_file: Annotated[Path, typer.Argument(help="The run spec, a TOML file.")],
    data: Annotated[
        Path, typer.Option(help="Holds raw/, catalog/ and results/.")
    ] = DATA,
    memory_budget: Annotated[
        int | None,
        typer.Option(
            parser=_size,
            metavar="SIZE",
            help="Memory for all the runs at once. Default: half the machine's.",
        ),
    ] = None,
    memory_per_run: Annotated[
        int | None,
        typer.Option(
            parser=_size,
            metavar="SIZE",
            help="The memory cap of each run, e.g. 4G. Default: 4G.",
        ),
    ] = None,
) -> None:
    """Run the backtests a spec file describes and store their results."""
    try:
        root = data.resolve()
        level = LogLevel.from_str(context.obj)
        settings = RunSettings(root / "catalog", log_level=level)
        _run(spec_file, _setup(root, settings, _memory(memory_budget, memory_per_run)))
    except Exception:
        logger.exception("run of %s failed", spec_file)
        raise typer.Exit(1) from None


def _memory(budget: int | None, per_run: int | None) -> Memory:
    return Memory(budget) if per_run is None else Memory(budget, per_run)


def _setup(data: Path, settings: RunSettings, memory: Memory) -> BatchSetup:
    return BatchSetup(
        store=ParquetResultStore(data / "results"),
        sources=lambda name: sources.source(name, SOURCES),
        folders=DataFolders(data / "raw", data / "catalog"),
        settings=settings,
        launcher=SystemdScope(),
        memory=memory,
    )


def _run(spec_file: Path, setup: BatchSetup) -> None:
    """Pre-flight every run of the spec file, then execute them in a batch."""
    runs = spec.load(spec_file)
    with _batch_bar() as bar:
        run_ids = batch(runs, setup, bar)
    for run_id in run_ids:
        logger.info("stored run %s in %s", run_id, setup.store.folder(run_id))


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


@app.command()
def ingest(
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
        Path,
        typer.Option("--data", help="Reads PATH/raw, writes PATH/catalog."),
    ] = DATA,
    reingest: Annotated[
        bool,
        typer.Option(
            help="Replace the catalog's instrument with a newer snapshot that "
            "differs, and rebuild its days."
        ),
    ] = False,
) -> None:
    """Write a source's raw files for a range of days into the catalog."""
    options = data.IngestOptions(data_root / "raw", data_root / "catalog")
    try:
        request = data.IngestRequest(
            tuple(symbol), start.date(), end.date(), tuple(data_type or ()), reingest
        )
        report = _ingest(source, request, options)
    except Exception:
        logger.exception("ingest from %s failed", source)
        raise typer.Exit(1) from None
    _log_ingest_summary(report)


def _ingest(
    name: str, request: data.IngestRequest, options: data.IngestOptions
) -> data.IngestReport:
    adapter = sources.source(name, SOURCES)
    with _ingest_bar() as bar:
        return data.ingest(adapter, request, replace(options, progress=bar))


def _log_ingest_summary(report: data.IngestReport) -> None:
    for each in report.having(data.IngestOutcome.MISSING):
        day = each.day
        logger.warning(
            "no raw file: %s %s %s", day.symbol, day.data, day.day.isoformat()
        )
    counts = (f"{len(report.having(each))} {each}" for each in data.IngestOutcome)
    logger.info("days: %s", ", ".join(counts))


@data_app.command()
def status(
    data_root: Annotated[
        Path, typer.Option("--data", help="Reads PATH/catalog.")
    ] = DATA,
    start: Annotated[
        datetime | None,
        typer.Option(formats=DAY, help="Check every day from this UTC day."),
    ] = None,
    end: Annotated[
        datetime | None,
        typer.Option(formats=DAY, help="Check every day up to this UTC day, included."),
    ] = None,
) -> None:
    """Show the symbols, data types and days in the catalog, and flag gaps."""
    try:
        window = _window(start, end)
        catalog = data.Catalog(data_root / "catalog")
        holdings = catalog.status(sources.known_gaps(SOURCES), window)
    except Exception:
        logger.exception("status of %s failed", data_root / "catalog")
        raise typer.Exit(1) from None
    typer.echo(_status_table(holdings))


def _window(start: datetime | None, end: datetime | None) -> data.Window | None:
    if start is None and end is None:
        return None
    if start is None or end is None:
        raise ValueError("give both --start and --end, or neither")
    last = end.date() + timedelta(days=1)
    return data.Window(_midnight(start.date()), _midnight(last))


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), UTC)


_STATUS_HEADER = ("instrument", "type", "first", "last", "days", "gaps", "known gaps")


def _status_table(holdings: tuple[data.Holding, ...]) -> str:
    if not holdings:
        return "the catalog is empty"
    return _table(_STATUS_HEADER, [_status_row(each) for each in holdings])


def _table(header: tuple[str, ...], body: list[tuple[str, ...]]) -> str:
    """Rows of left-aligned columns, as wide as their widest cell."""
    rows = [header, *body]
    widths = [max(len(row[column]) for row in rows) for column in range(len(header))]
    return "\n".join(
        "  ".join(
            cell.ljust(width) for cell, width in zip(row, widths, strict=True)
        ).rstrip()
        for row in rows
    )


def _status_row(holding: data.Holding) -> tuple[str, ...]:
    return (
        str(holding.instrument_id),
        holding.data_type.__name__,
        holding.first.isoformat(),
        holding.last.isoformat(),
        str(holding.days),
        _day_ranges(holding.gaps),
        _day_ranges(holding.known_gaps),
    )


def _day_ranges(days: tuple[date, ...]) -> str:
    """Days as comma-separated runs of consecutive days, e.g. ``a..b,c``."""
    if not days:
        return "-"
    runs: list[list[date]] = []
    for day in days:
        if runs and day - runs[-1][-1] == timedelta(days=1):
            runs[-1].append(day)
        else:
            runs.append([day])
    return ",".join(_day_run(each) for each in runs)


def _day_run(days: list[date]) -> str:
    if len(days) == 1:
        return days[0].isoformat()
    return f"{days[0].isoformat()}..{days[-1].isoformat()}"


_RUNS_HEADER = (
    "run_id",
    "strategy",
    "part",
    "start",
    "end",
    "net_return",
    "sharpe",
    "max_drawdown",
    "trade_count",
)


@runs_app.command("list")
def list_runs(
    data_root: Annotated[
        Path, typer.Option("--data", help="Reads PATH/results.")
    ] = DATA,
    strategy: Annotated[
        str | None, typer.Option(help="Only this strategy's import path.")
    ] = None,
    part: Annotated[str | None, typer.Option(help="Only this part.")] = None,
) -> None:
    """Show one row per finished run, oldest first."""
    try:
        runs = ParquetResultStore(data_root / "results").runs(strategy, part)
    except Exception:
        logger.exception("listing the runs in %s failed", data_root / "results")
        raise typer.Exit(1) from None
    typer.echo(_runs_table(runs))


def _runs_table(runs: pd.DataFrame) -> str:
    if runs.empty:
        return "no runs"
    records = runs.to_dict("records")
    return _table(_RUNS_HEADER, [_runs_row(each) for each in records])


def _runs_row(record: Mapping[Hashable, object]) -> tuple[str, ...]:
    return tuple(_cell(record[column]) for column in _RUNS_HEADER)


def _cell(value: object) -> str:
    if _missing(value):
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


@runs_app.command()
def show(
    run_id: Annotated[str, typer.Argument(help="The run's id.")],
    data_root: Annotated[
        Path, typer.Option("--data", help="Reads PATH/results.")
    ] = DATA,
) -> None:
    """Show a run's summary and its resolved spec."""
    try:
        text = _shown(ParquetResultStore(data_root / "results"), run_id)
    except Exception:
        logger.exception("showing run %s failed", run_id)
        raise typer.Exit(1) from None
    typer.echo(text)


@runs_app.command()
def delete(
    run_id: Annotated[str, typer.Argument(help="The run's id.")],
    data_root: Annotated[
        Path, typer.Option("--data", help="Deletes from PATH/results.")
    ] = DATA,
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask first.")] = False,
) -> None:
    """Delete a run's folder, a failed run's partial one included."""
    if not yes:
        typer.confirm(f"delete run {run_id}?", abort=True)
    try:
        ParquetResultStore(data_root / "results").delete(run_id)
    except Exception:
        logger.exception("deleting run %s failed", run_id)
        raise typer.Exit(1) from None


def _shown(store: ResultStore, run_id: str) -> str:
    document = json.dumps(store.spec(run_id), indent=2)
    return f"{_summary_lines(store, run_id)}\n\n{document}"


def _summary_lines(store: ResultStore, run_id: str) -> str:
    try:
        [record] = store.load(run_id, "summary").to_dict("records")
    except MissingTableError:
        return f"run {run_id} has no summary: it did not finish"
    width = max(len(str(column)) for column in record)
    return "\n".join(
        f"{str(column).ljust(width)}  {_detail(value)}"
        for column, value in record.items()
    )


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


def _detail(value: object) -> str:
    if isinstance(value, np.ndarray):
        return ", ".join(str(each) for each in value) or "-"
    if _missing(value):
        return "-"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


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
    with _progress(TextColumn("{task.fields[size]}")) as progress:
        yield _DownloadBar(progress)


class _IngestBar:
    """Days done out of those planned."""

    def __init__(self, progress: Progress) -> None:
        self._progress = progress
        self._task = progress.add_task("ingest", total=None)

    def planned(self, days: int) -> None:
        self._progress.update(self._task, total=days)

    def finished(self, result: data.DayResult) -> None:
        self._progress.advance(self._task)


@contextmanager
def _ingest_bar() -> Iterator[_IngestBar]:
    with _progress() as progress:
        yield _IngestBar(progress)


class _BatchBar:
    """Runs done out of those planned."""

    def __init__(self, progress: Progress) -> None:
        self._progress = progress
        self._task = progress.add_task("runs", total=None)

    def planned(self, runs: int) -> None:
        self._progress.update(self._task, total=runs)

    def finished(self, run_id: str) -> None:
        self._progress.advance(self._task)


@contextmanager
def _batch_bar() -> Iterator[_BatchBar]:
    with _progress() as progress:
        yield _BatchBar(progress)


@contextmanager
def _progress(*extra: TextColumn) -> Iterator[Progress]:
    with Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        *extra,
        TimeElapsedColumn(),
        console=Console(stderr=True),
    ) as progress:
        yield progress


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
