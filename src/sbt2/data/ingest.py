import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from itertools import product
from pathlib import Path
from typing import Any, Protocol

import pandas as pd

from sbt2.data.catalog_writer import CatalogWriter, DayFile
from sbt2.data.days import data_types, days, is_known_gap
from sbt2.data.layout import Bounds
from sbt2.sources import Source

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DAY_NANOS = 86_400_000_000_000
_TIMESTAMPS = ("ts_event", "ts_init")


class IngestOutcome(StrEnum):
    WRITTEN = "written"
    EMPTY = "empty"
    SKIPPED = "skipped"
    MISSING = "missing"


class NoSnapshotError(LookupError):
    pass


class InstrumentChangedError(RuntimeError):
    """The newest snapshot differs from the instrument the catalog was built with."""


class OutsideDayError(ValueError):
    """A parsed record falls outside the UTC day of the raw file it came from."""


@dataclass(frozen=True)
class IngestRequest:
    """Symbols over an inclusive range of UTC days.

    ``data`` names the data types to ingest by their nautilus type name; empty
    means every type the source serves. ``reingest`` allows a newer instrument
    snapshot to replace the catalog's, which removes the instrument's days.
    """

    symbols: tuple[str, ...]
    start: date
    end: date
    data: tuple[str, ...] = ()
    reingest: bool = False

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"the range ends on {self.end}, before {self.start}")


@dataclass(frozen=True)
class Day:
    """One day file: ``data`` is a nautilus type name."""

    symbol: str
    data: str
    day: date


@dataclass(frozen=True)
class DayResult:
    day: Day
    outcome: IngestOutcome


@dataclass(frozen=True)
class IngestReport:
    results: tuple[DayResult, ...]

    def having(self, outcome: IngestOutcome) -> tuple[DayResult, ...]:
        return tuple(each for each in self.results if each.outcome is outcome)


class IngestProgress(Protocol):
    def planned(self, days: int) -> None: ...

    def finished(self, result: DayResult) -> None: ...


class _Silent:
    def planned(self, days: int) -> None:
        pass

    def finished(self, result: DayResult) -> None:
        pass


@dataclass(frozen=True)
class IngestOptions:
    raw: Path
    catalog: Path
    progress: IngestProgress = field(default_factory=_Silent)


@dataclass(frozen=True)
class _Job:
    source: Source
    request: IngestRequest
    options: IngestOptions
    writer: CatalogWriter


def ingest(
    source: Source, request: IngestRequest, options: IngestOptions
) -> IngestReport:
    """Write the request's raw files from ``options.raw`` into the catalog.

    Each symbol's instrument comes from its newest snapshot. Days already in
    the catalog are skipped, and days without a raw file are reported as missing.
    """
    options.catalog.mkdir(parents=True, exist_ok=True)
    job = _Job(source, request, options, CatalogWriter(options.catalog))
    types = data_types(source, request.data)
    options.progress.planned(_planned_days(request, types))
    results = [
        result
        for symbol in request.symbols
        for result in _ingest_symbol(job, symbol, types)
    ]
    return IngestReport(tuple(results))


def _planned_days(request: IngestRequest, types: Sequence[type]) -> int:
    span = (request.end - request.start).days + 1
    return len(request.symbols) * len(types) * span


def _ingest_symbol(
    job: _Job, symbol: str, types: Sequence[type]
) -> Iterator[DayResult]:
    instrument = _pinned_instrument(job, symbol)
    span = days(job.request.start, job.request.end)
    for data_type, day in product(types, span):
        if not is_known_gap(job.source, symbol, data_type, day):
            result = _ingest_day(job, instrument, Day(symbol, data_type.__name__, day))
            job.options.progress.finished(result)
            yield result


def _pinned_instrument(job: _Job, symbol: str) -> Any:
    """The newest snapshot's instrument, once the catalog holds it."""
    newest = job.source.parse_instrument(_newest_snapshot(job, symbol))
    stored = job.writer.instrument(newest.id)
    if stored is None:
        job.writer.write_instrument(newest)
        return newest
    if _same_spec(stored, newest):
        return stored
    if not job.request.reingest:
        raise InstrumentChangedError(
            f"the {symbol} snapshot of {_day_of(newest.ts_init)} differs from the "
            f"catalog's instrument of {_day_of(stored.ts_init)}; re-ingest to replace it"
        )
    job.writer.remove(newest.id, job.source.data_types)
    job.writer.write_instrument(newest)
    return newest


def _newest_snapshot(job: _Job, symbol: str) -> Path:
    candidate = job.source.instrument_snapshot(symbol, date.min).path
    folder = job.options.raw / candidate.parent
    taken = [each for each in _dates_in(folder) if _is_snapshot(job, symbol, each)]
    if not taken:
        raise NoSnapshotError(f"no {symbol} instrument snapshot in {folder}")
    return job.options.raw / job.source.instrument_snapshot(symbol, max(taken)).path


def _dates_in(folder: Path) -> Iterator[date]:
    if not folder.is_dir():
        return
    for each in folder.iterdir():
        found = _ISO_DATE.search(each.name)
        if found is not None:
            yield date.fromisoformat(found[0])


def _is_snapshot(job: _Job, symbol: str, taken_on: date) -> bool:
    path = job.options.raw / job.source.instrument_snapshot(symbol, taken_on).path
    return path.is_file()


def _same_spec(stored: Any, newest: Any) -> bool:
    return _spec(stored) == _spec(newest)


def _spec(instrument: Any) -> dict[str, Any]:
    fields = instrument.to_dict()
    return {key: value for key, value in fields.items() if key not in _TIMESTAMPS}


def _day_of(nanos: int) -> date:
    return datetime.fromtimestamp(nanos // 1_000_000_000, UTC).date()


def _ingest_day(job: _Job, instrument: Any, day: Day) -> DayResult:
    data_type = _data_type(job.source, day.data)
    target = DayFile(data_type, instrument, _bounds(day.day))
    if job.writer.has(target):
        return DayResult(day, IngestOutcome.SKIPPED)
    raw = job.options.raw / job.source.day_file(day.symbol, data_type, day.day).path
    if not raw.is_file():
        return DayResult(day, IngestOutcome.MISSING)
    records = list(job.source.parse(raw, data_type, instrument))
    _check_inside(records, target.bounds, raw)
    job.writer.write(target, records)
    outcome = IngestOutcome.WRITTEN if records else IngestOutcome.EMPTY
    return DayResult(day, outcome)


def _data_type(source: Source, name: str) -> type:
    return next(each for each in source.data_types if each.__name__ == name)


def _bounds(day: date) -> Bounds:
    start = pd.Timestamp(day, tz="UTC").value
    return start, start + _DAY_NANOS - 1


def _check_inside(records: Sequence[Any], bounds: Bounds, raw: Path) -> None:
    start, end = bounds
    outside = [each for each in records if not start <= each.ts_init <= end]
    if outside:
        raise OutsideDayError(
            f"{raw}: {len(outside)} records outside its UTC day, "
            f"the first at ts_init {outside[0].ts_init}"
        )
