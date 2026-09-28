import logging
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from operator import attrgetter
from pathlib import Path

import nautilus_trader.model

from sbt2.data import (
    Catalog,
    Coverage,
    DownloadOptions,
    DownloadRequest,
    IngestOptions,
    IngestRequest,
    NoSnapshotError,
    Outcome,
    Selection,
    Window,
    download,
    ingest,
)
from sbt2.data.sources import Gap, Source
from sbt2.spec import ResolvedRunSpec

logger = logging.getLogger(__name__)

# Nautilus keeps at most this many portfolio snapshots per account, in a ring buffer.
SNAPSHOT_BUFFER = 1_000_000


@dataclass(frozen=True)
class DataFolders:
    raw: Path
    catalog: Path


class PreflightError(RuntimeError):
    pass


class SnapshotBufferError(PreflightError):
    pass


class MissingDataError(PreflightError):
    pass


class InstrumentAssetClassError(PreflightError):
    pass


class LiquidationWithoutQuotesError(PreflightError):
    pass


def preflight(
    spec: ResolvedRunSpec, source: Source, folders: DataFolders
) -> tuple[Gap, ...]:
    """Check that ``spec`` can run, fetching the data it lacks from ``source``.

    Returns the known-gap days the run will skip.
    """
    _check_snapshots(spec)
    _check_liquidation(spec)
    known_gaps = _check_coverage(spec, source, folders)
    _check_instruments(spec, Catalog(folders.catalog))
    return known_gaps


def _check_snapshots(spec: ResolvedRunSpec) -> None:
    interval = timedelta(milliseconds=spec.equity_interval_ms)
    snapshots = -((spec.start - spec.end) // interval)
    if snapshots > SNAPSHOT_BUFFER:
        raise SnapshotBufferError(
            f"the run from {spec.start} to {spec.end} takes {snapshots:,} snapshots "
            f"at {interval}; nautilus keeps at most {SNAPSHOT_BUFFER:,}"
        )


def _check_liquidation(spec: ResolvedRunSpec) -> None:
    streamed = {str(each["data_type"]) for each in spec.data}
    if spec.venue.get("liquidation_enabled") and "QuoteTick" not in streamed:
        raise LiquidationWithoutQuotesError(
            "the run has liquidation on but streams no quotes; nautilus liquidates "
            "only on quotes, so it never would. Set liquidation = false"
        )


def _check_coverage(
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


def _check_instruments(spec: ResolvedRunSpec, catalog: Catalog) -> None:
    ids = spec.strategy.instruments
    instruments = catalog.instruments(ids)
    absent = [str(each) for each in ids if each not in instruments]
    if absent:
        raise MissingDataError(f"the catalog has no instrument {', '.join(absent)}")
    profile = spec.asset
    for each in instruments.values():
        if not profile.covers(each):
            raise InstrumentAssetClassError(
                f"{each.id} is {each.asset_class.name}/{each.instrument_class.name}, "
                f"not the run's {profile.asset_class.name}/"
                f"{profile.instrument_class.name}"
            )


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
    report = download(
        source,
        DownloadRequest(symbols, first, last, types),
        DownloadOptions(folders.raw),
    )
    for each in report.having(Outcome.FAILED):
        logger.warning("failed to fetch %s: %s", each.item.raw.path, each.reason)
    try:
        ingest(
            source,
            IngestRequest(symbols, first, last, types),
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
    [first, *_] = spec.data
    return Selection(
        tuple(first["instrument_ids"]),
        tuple(
            getattr(nautilus_trader.model, str(each["data_type"])) for each in spec.data
        ),
        Window(first["start_time"], first["end_time"]),
    )
