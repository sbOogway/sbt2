import json
import logging
import math
import re
import sys
from collections.abc import Generator, Hashable, Mapping
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
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from sbt2 import data, results, spec
from sbt2.config import ROOT, SOURCES, Root
from sbt2.results import (
    Benchmark,
    MissingTableError,
    ParquetResultStore,
    ResultStore,
    StoredRun,
    build_benchmark,
)
from sbt2.run import (
    BatchSetup,
    DataFolders,
    Memory,
    RunSettings,
    SystemdScope,
    batch,
)
from sbt2.strategy import import_strategy

DAY = ["%Y-%m-%d"]
SIZE = re.compile(r"(\d+)([KMGT]?)")
SIZE_UNITS = {"": 0, "K": 10, "M": 20, "G": 30, "T": 40}
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
data_app = typer.Typer(no_args_is_help=True, help="Inspect the catalog.")
app.add_typer(data_app, name="data")
runs_app = typer.Typer(no_args_is_help=True, help="Query and manage stored runs.")
app.add_typer(runs_app, name="runs")
report_app = typer.Typer(no_args_is_help=True, help="Report on stored runs.")
app.add_typer(report_app, name="report")
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


@contextmanager
def _failing(action: str, *args: object) -> Generator[None]:
    """Logs an exception as the action failing, and exits with code 1."""
    try:
        yield
    except Exception:
        logger.exception("%s failed", action % args)
        raise typer.Exit(1) from None


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
    ] = ROOT,
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
    with _failing("run of %s", spec_file):
        root = Root(data.resolve())
        level = LogLevel.from_str(context.obj)
        settings = RunSettings(root.catalog, log_level=level)
        _run(spec_file, _setup(root, settings, _memory(memory_budget, memory_per_run)))


def _memory(budget: int | None, per_run: int | None) -> Memory:
    return Memory(budget) if per_run is None else Memory(budget, per_run)


def _setup(root: Root, settings: RunSettings, memory: Memory) -> BatchSetup:
    return BatchSetup(
        store=ParquetResultStore(root.results),
        sources=lambda name: data.source(name, SOURCES),
        folders=DataFolders(root.raw, root.catalog),
        settings=settings,
        launcher=SystemdScope(),
        memory=memory,
    )


def _run(spec_file: Path, setup: BatchSetup) -> None:
    """Pre-flight every run of the spec file, then execute them in a batch."""
    runs = spec.load(spec_file)
    with _bar("runs") as bar:
        run_ids = batch(runs, setup, bar)
    for run_id in run_ids:
        logger.info("stored run %s in %s", run_id, setup.store.folder(run_id))
    typer.echo(_headline_tables(setup.store, run_ids))


_HEADLINE_HEADER = (
    "run_id",
    "strategy",
    "net_return",
    "annualized_return",
    "sharpe",
    "max_drawdown",
    "trade_count",
    "total_fees",
    "total_carry",
)


def _headline_tables(store: ResultStore, run_ids: tuple[str, ...]) -> str:
    """One table of the runs' headline metrics per part, in split order."""
    runs = store.runs()
    runs = runs.loc[runs["run_id"].isin(run_ids)]
    return "\n\n".join(
        f"{part}\n{_frame_table(runs.loc[runs['part'] == part], _HEADLINE_HEADER)}"
        for part in spec.PARTS
        if (runs["part"] == part).any()
    )


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
    ] = ROOT,
    concurrency: Annotated[int, typer.Option(min=1)] = 8,
    retries: Annotated[int, typer.Option(min=0, help="Per file.")] = 5,
) -> None:
    """Fetch a source's raw files for a range of days, and today's instruments."""
    options = data.DownloadOptions(Root(data_root).raw, concurrency, retries)
    with _failing("download from %s", source):
        days = data.DayRange(
            tuple(symbol), start.date(), end.date(), tuple(data_type or ())
        )
        request = data.DownloadRequest(days)
        tally = _download(source, request, options)
    _log_summary(tally)
    if tally.having(data.Outcome.FAILED):
        raise typer.Exit(1)


def _download(
    name: str, request: data.DownloadRequest, options: data.DownloadOptions
) -> data.Tally[data.FileResult]:
    adapter = data.source(name, SOURCES)
    with _download_bar() as bar:
        return data.download(adapter, request, replace(options, progress=bar))


def _log_summary(tally: data.Tally[data.FileResult]) -> None:
    for each in tally.having(data.Outcome.MISSING):
        logger.warning("missing at the source: %s", _described(each.item))
    for each in tally.having(data.Outcome.FAILED):
        logger.error("failed: %s: %s", _described(each.item), each.reason)
    counts = (f"{len(tally.having(each))} {each}" for each in data.Outcome)
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
    ] = ROOT,
    reingest: Annotated[
        bool,
        typer.Option(
            help="Replace the catalog's instrument with a newer snapshot that "
            "differs, and rebuild its days."
        ),
    ] = False,
) -> None:
    """Write a source's raw files for a range of days into the catalog."""
    root = Root(data_root)
    options = data.IngestOptions(root.raw, root.catalog)
    with _failing("ingest from %s", source):
        days = data.DayRange(
            tuple(symbol), start.date(), end.date(), tuple(data_type or ())
        )
        request = data.IngestRequest(days, reingest)
        tally = _ingest(source, request, options)
    _log_ingest_summary(tally)


def _ingest(
    name: str, request: data.IngestRequest, options: data.IngestOptions
) -> data.Tally[data.DayResult]:
    adapter = data.source(name, SOURCES)
    with _bar("ingest") as bar:
        return data.ingest(adapter, request, replace(options, progress=bar))


def _log_ingest_summary(tally: data.Tally[data.DayResult]) -> None:
    for each in tally.having(data.IngestOutcome.MISSING):
        day = each.day
        logger.warning(
            "no raw file: %s %s %s", day.symbol, day.data, day.day.isoformat()
        )
    counts = (f"{len(tally.having(each))} {each}" for each in data.IngestOutcome)
    logger.info("days: %s", ", ".join(counts))


@data_app.command()
def status(
    data_root: Annotated[
        Path, typer.Option("--data", help="Reads PATH/catalog.")
    ] = ROOT,
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
    folder = Root(data_root).catalog
    with _failing("status of %s", folder):
        window = _window(start, end)
        catalog = data.Catalog(folder)
        holdings = catalog.status(data.known_gaps(SOURCES), window)
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
    ] = ROOT,
    strategy: Annotated[
        str | None, typer.Option(help="Only this strategy's import path.")
    ] = None,
    part: Annotated[str | None, typer.Option(help="Only this part.")] = None,
) -> None:
    """Show one row per finished run, oldest first."""
    with _failing("listing the runs in %s", Root(data_root).results):
        runs = _store(data_root).runs(strategy, part)
    typer.echo(_runs_table(runs))


def _store(data_root: Path) -> ParquetResultStore:
    return ParquetResultStore(Root(data_root).results)


def _runs_table(runs: pd.DataFrame) -> str:
    if runs.empty:
        return "no runs"
    return _frame_table(runs, _RUNS_HEADER)


def _frame_table(frame: pd.DataFrame, columns: tuple[str, ...]) -> str:
    """The frame's ``columns``, one row per record, cells as ``runs list``
    prints them."""
    records = frame.to_dict("records")
    return _table(columns, [_row(each, columns) for each in records])


def _row(
    record: Mapping[Hashable, object], columns: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(_cell(record[column]) for column in columns)


def _cell(value: object) -> str:
    if isinstance(value, float) and not math.isnan(value):
        return f"{value:.4f}"
    return _text(value)


@runs_app.command()
def show(
    run_id: Annotated[str, typer.Argument(help="The run's id.")],
    data_root: Annotated[
        Path, typer.Option("--data", help="Reads PATH/results.")
    ] = ROOT,
) -> None:
    """Show a run's summary and its resolved spec."""
    with _failing("showing run %s", run_id):
        text = _shown(_store(data_root), run_id)
    typer.echo(text)


@runs_app.command()
def delete(
    run_id: Annotated[str, typer.Argument(help="The run's id.")],
    data_root: Annotated[
        Path, typer.Option("--data", help="Deletes from PATH/results.")
    ] = ROOT,
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask first.")] = False,
) -> None:
    """Delete a run's folder, a failed run's partial one included."""
    if not yes:
        typer.confirm(f"delete run {run_id}?", abort=True)
    with _failing("deleting run %s", run_id):
        _store(data_root).delete(run_id)


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


def _detail(value: object) -> str:
    if isinstance(value, np.ndarray):
        return ", ".join(str(each) for each in value) or "-"
    return _text(value)


def _text(value: object) -> str:
    """A stored value as ``runs list`` and ``runs show`` print it."""
    if _missing(value):
        return "-"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _missing(value: object) -> bool:
    return value is None or (isinstance(value, float) and math.isnan(value))


@report_app.command("tearsheet")
def report_tearsheet(
    run_id: Annotated[str, typer.Argument(help="The run's id.")],
    data_root: Annotated[
        Path, typer.Option("--data", help="Reads PATH/results and PATH/catalog.")
    ] = ROOT,
    benchmark: Annotated[
        str | None,
        typer.Option(
            metavar="NAME[:ARG]",
            help="buy-and-hold[:INSTRUMENT], equal-weight, external:FILE or none. "
            "Default: the strategy's.",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(help="Default: tearsheet.html in the run's folder."),
    ] = None,
) -> None:
    """Write a run's tearsheet, against a benchmark."""
    root = Root(data_root)
    with _failing("tearsheet of run %s", run_id):
        store = ParquetResultStore(root.results)
        stored = store.stored_run(run_id)
        path = output or store.folder(run_id) / "tearsheet.html"
        priced = stored.priced(data.Catalog(root.catalog))
        results.tearsheet(priced, path, _benchmark(benchmark, stored))
    logger.info("wrote the tearsheet of run %s to %s", run_id, path)


_PARTS_HEADER = (
    "part",
    "run_id",
    "start",
    "end",
    "net_return",
    "annualized_return",
    "sharpe",
    "max_drawdown",
    "trade_count",
    "total_fees",
    "total_carry",
)


@report_app.command("parts")
def report_parts(
    run_id: Annotated[str, typer.Argument(help="The run's id.")],
    data_root: Annotated[
        Path, typer.Option("--data", help="Reads PATH/results.")
    ] = ROOT,
) -> None:
    """Show each part a run's parameters were run on, then how the headline
    metrics change from one part to the next."""
    with _failing("comparing the parts of run %s", run_id):
        parts = results.compare_parts(_store(data_root), run_id)
        change = results.degradation(parts)
    typer.echo(f"{_parts_table(parts)}\n\n{_change_table(change)}")


def _parts_table(parts: pd.DataFrame) -> str:
    return _frame_table(parts.reset_index(), _PARTS_HEADER)


def _change_table(change: pd.DataFrame) -> str:
    """One row per headline metric, one column per part and per change."""
    rows = change.rename_axis("metric").reset_index()
    return _frame_table(rows, ("metric", *(str(each) for each in change.columns)))


@report_app.command("batch")
def report_batch(
    batch_id: Annotated[str, typer.Argument(help="The batch's id.")],
    data_root: Annotated[
        Path, typer.Option("--data", help="Reads PATH/results.")
    ] = ROOT,
) -> None:
    """Show one row per run of a batch: the parameters that vary across it,
    then the headline metrics."""
    with _failing("reporting batch %s", batch_id):
        table = results.batch_table(_store(data_root), batch_id)
    columns = ("run_id", *(str(each) for each in table.columns))
    typer.echo(_frame_table(table.reset_index(), columns))


def _benchmark(option: str | None, stored: StoredRun) -> Benchmark | None:
    """The benchmark ``NAME[:ARG]`` names, the strategy's own without one."""
    if option is None:
        return import_strategy(stored.spec.strategy.strategy).benchmark
    name, _, argument = option.partition(":")
    return build_benchmark(name, argument or None)


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


@contextmanager
def _bar(description: str) -> Generator[_Bar]:
    with _progress() as progress:
        yield _Bar(progress, progress.add_task(description, total=None))


@contextmanager
def _download_bar() -> Generator[_DownloadBar]:
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
