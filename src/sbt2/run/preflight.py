from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import nautilus_trader.model

from sbt2.data import Catalog, Coverage, Selection, Window
from sbt2.sources import Gap, Source
from sbt2.spec import ResolvedRunSpec

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


def preflight(
    spec: ResolvedRunSpec, source: Source, folders: DataFolders
) -> tuple[Gap, ...]:
    """Check that ``spec`` can run, fetching the data it lacks from ``source``.

    Returns the known-gap days the run will skip.
    """
    _check_snapshots(spec)
    uncovered = _uncovered(spec, Catalog(folders.catalog), source.known_gaps)
    if uncovered.missing:
        described = ", ".join(map(_described, uncovered.missing))
        raise MissingDataError(f"the catalog lacks {described}")
    return uncovered.known_gaps


def _check_snapshots(spec: ResolvedRunSpec) -> None:
    interval = timedelta(milliseconds=spec.equity_interval_ms)
    snapshots = -((spec.start - spec.end) // interval)
    if snapshots > SNAPSHOT_BUFFER:
        raise SnapshotBufferError(
            f"the run from {spec.start} to {spec.end} takes {snapshots:,} snapshots "
            f"at {interval}; nautilus keeps at most {SNAPSHOT_BUFFER:,}"
        )


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
        missing=tuple(_gaps(coverage, trading, _missing)),
        known_gaps=tuple(_gaps(coverage, trading, _known_gaps)),
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


def _missing(coverage: Coverage) -> tuple[date, ...]:
    return coverage.missing


def _known_gaps(coverage: Coverage) -> tuple[date, ...]:
    return coverage.known_gaps


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


def _described(gap: Gap) -> str:
    return f"{gap.instrument_id} {gap.data_type.__name__} {gap.day.isoformat()}"
