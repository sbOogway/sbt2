import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date
from operator import attrgetter
from pathlib import Path

from sbt2.core.data import (
    Catalog,
    Coverage,
    DayRange,
    DownloadOptions,
    DownloadRequest,
    Gap,
    IngestOptions,
    IngestRequest,
    NoSnapshotError,
    Outcome,
    Selection,
    Source,
    Window,
    download,
    ingest,
)
from sbt2.core.run.preflight.errors import MissingDataError
from sbt2.core.spec import ResolvedRunSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DataFolders:
    raw: Path
    catalog: Path


def check_coverage(
    spec: ResolvedRunSpec, source: Source, folders: DataFolders
) -> tuple[Gap, ...]:
    """Fetch the days the catalog lacks, and return the known gaps."""
    folders.catalog.mkdir(parents=True, exist_ok=True)
    uncovered = _uncovered(spec, Catalog(folders.catalog), source.known_gaps)
    if uncovered.missing:
        _fetch(source, uncovered.missing, folders)
        uncovered = _uncovered(spec, Catalog(folders.catalog), source.known_gaps)
    if uncovered.missing:
        described = ", ".join(map(str, uncovered.missing))
        raise MissingDataError(f"the catalog lacks {described}")
    return uncovered.known_gaps


def _fetch(source: Source, missing: tuple[Gap, ...], folders: DataFolders) -> None:
    """Download and ingest the span of the missing days."""
    symbols = tuple(sorted({source.symbol(each.instrument_id) for each in missing}))
    types = tuple(sorted({each.data_type.__name__ for each in missing}))
    first, last = min(each.day for each in missing), max(each.day for each in missing)
    logger.info(
        "fetching %s %s from %s to %s",
        ", ".join(symbols),
        ", ".join(types),
        first,
        last,
    )
    days = DayRange(symbols, first, last, types)
    tally = download(source, DownloadRequest(days), DownloadOptions(folders.raw))
    for each in tally.having(Outcome.FAILED):
        logger.warning("failed to fetch %s: %s", each.item.raw.path, each.reason)
    try:
        ingest(
            source,
            IngestRequest(days),
            IngestOptions(folders.raw, folders.catalog),
        )
    except NoSnapshotError as error:
        ids = ", ".join(sorted({str(each.instrument_id) for each in missing}))
        raise MissingDataError(f"no instrument for {ids}: {error}") from error


@dataclass(frozen=True)
class _Uncovered:
    """The run's days without data, on the asset class's trading days."""

    missing: tuple[Gap, ...]
    known_gaps: tuple[Gap, ...]


def _uncovered(
    spec: ResolvedRunSpec, catalog: Catalog, known_gaps: frozenset[Gap]
) -> _Uncovered:
    selection = _selection(spec)
    window = selection.window
    trading = frozenset(spec.asset.calendar.trading_days(window.start, window.end))
    coverage = catalog.coverage(selection, known_gaps)
    return _Uncovered(
        missing=tuple(_gaps(coverage, trading, attrgetter("missing"))),
        known_gaps=tuple(_gaps(coverage, trading, attrgetter("known_gaps"))),
    )


def _gaps(
    coverage: Iterable[Coverage],
    trading: frozenset[date],
    days: Callable[[Coverage], tuple[date, ...]],
) -> Iterator[Gap]:
    for each in coverage:
        for day in days(each):
            if day in trading:
                yield Gap(each.instrument_id, each.data_type, day)


def _selection(spec: ResolvedRunSpec) -> Selection:
    """The instruments, data types and window the run streams."""
    return Selection(spec.instrument_ids, spec.data_types, Window(*spec.data_window))
