from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from functools import cached_property
from pathlib import Path
from typing import Any, Self

import pandas as pd
from nautilus_trader.model import InstrumentId, NautilusDataType
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.core.data.catalog.stored import (
    STORED,
    StoredType,
    UnstoredDataTypeError,
    nautilus_type,
    stored_type,
)
from sbt2.core.data.days import days
from sbt2.core.data.sources import Gap

type Interval = tuple[int, int]


@dataclass(frozen=True)
class Window:
    """The half-open time range ``[start, end)``, in tz-aware datetimes."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError(f"the window {self.start} to {self.end} has no time zone")
        if self.end <= self.start:
            raise ValueError(f"the window ends on {self.end}, before {self.start}")

    @classmethod
    def of_days(cls, first: date, last: date) -> Self:
        """The UTC days from ``first`` to ``last``, both included."""
        return cls(_midnight(first), _midnight(last + timedelta(days=1)))

    @property
    def nanos(self) -> Interval:
        """The window's first and last nanosecond, both included."""
        return _nanos(self.start), _nanos(self.end) - 1

    @property
    def days(self) -> tuple[date, ...]:
        """The UTC days the window touches."""
        first, last = self.nanos
        return tuple(days(_day(first), _day(last)))


@dataclass(frozen=True)
class Selection:
    instrument_ids: tuple[InstrumentId, ...]
    data_types: tuple[type, ...]
    window: Window


@dataclass(frozen=True)
class Coverage:
    """The days of a window without data, and those of them that are known gaps."""

    instrument_id: InstrumentId
    data_type: type
    missing: tuple[date, ...]
    known_gaps: tuple[date, ...]


@dataclass(frozen=True)
class Holding:
    """What the catalog holds of one data type for one instrument.

    ``days`` counts the covered days from ``first`` to ``last``. ``gaps`` and
    ``known_gaps`` are the uncovered days between them, or in the window asked for.
    """

    instrument_id: InstrumentId
    data_type: type
    first: date
    last: date
    days: int
    gaps: tuple[date, ...]
    known_gaps: tuple[date, ...]


@dataclass(frozen=True)
class _Series:
    """An instrument's data of one type; the type need not be one sbt2 stores."""

    instrument_id: InstrumentId
    data_type: type

    @property
    def nautilus_type(self) -> NautilusDataType:
        return nautilus_type(self.data_type)

    @property
    def identifier(self) -> str:
        try:
            stored = stored_type(self.data_type)
        except UnstoredDataTypeError:
            return str(self.instrument_id)
        return stored.identifier(self.instrument_id)

    def split(
        self, uncovered: Iterable[date], known_gaps: frozenset[Gap]
    ) -> tuple[tuple[date, ...], tuple[date, ...]]:
        """The uncovered days that are not known gaps, and those that are."""
        missing: list[date] = []
        known: list[date] = []
        for each in uncovered:
            gap = Gap(self.instrument_id, self.data_type, each)
            (known if gap in known_gaps else missing).append(each)
        return tuple(missing), tuple(known)


class Catalog:
    """Reads a nautilus catalog; the only way sbt2 does."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def coverage(
        self, selection: Selection, known_gaps: frozenset[Gap] = frozenset()
    ) -> tuple[Coverage, ...]:
        """One coverage per instrument and data type, in the selection's order."""
        return tuple(
            self._coverage(
                _Series(instrument_id, data_type), selection.window, known_gaps
            )
            for instrument_id in selection.instrument_ids
            for data_type in selection.data_types
        )

    def instruments(
        self, instrument_ids: Iterable[InstrumentId]
    ) -> Mapping[InstrumentId, Any]:
        """The latest version of each instrument; ids not in the catalog are absent."""
        ids = [str(each) for each in instrument_ids]
        latest: dict[InstrumentId, Any] = {}
        for each in sorted(
            self._nautilus.instruments(instrument_ids=ids), key=_ts_init
        ):
            latest[each.id] = each
        return latest

    def frame(
        self, instrument_id: InstrumentId, data_type: type, window: Window
    ) -> pd.DataFrame:
        """The instrument's ``data_type`` records in the window, indexed by event time."""
        records = self._records(_Series(instrument_id, data_type), window)
        return stored_type(data_type).frame(records)

    def status(
        self, known_gaps: frozenset[Gap], window: Window | None = None
    ) -> tuple[Holding, ...]:
        """A holding per instrument and data type the catalog has files for."""
        if not self._path.is_dir():
            return ()
        return tuple(
            self._holding(_Series(instrument_id, stored.data_type), known_gaps, window)
            for stored in STORED
            for instrument_id in self._instrument_ids(stored)
        )

    @cached_property
    def _nautilus(self) -> ParquetDataCatalog:
        return ParquetDataCatalog(str(self._path))

    def _coverage(
        self, series: _Series, window: Window, known_gaps: frozenset[Gap]
    ) -> Coverage:
        first, last = window.nanos
        intervals = self._nautilus.get_missing_intervals_for_request(
            first, last, series.nautilus_type, series.identifier
        )
        missing, known = series.split(
            _days_of(_clipped(intervals, window.nanos)), known_gaps
        )
        return Coverage(series.instrument_id, series.data_type, missing, known)

    def _holding(
        self, series: _Series, known_gaps: frozenset[Gap], window: Window | None
    ) -> Holding:
        covered = self._covered_days(series)
        checked = window.days if window else tuple(days(covered[0], covered[-1]))
        present = set(covered)
        uncovered = [each for each in checked if each not in present]
        gaps, known = series.split(uncovered, known_gaps)
        return Holding(
            series.instrument_id,
            series.data_type,
            covered[0],
            covered[-1],
            len(covered),
            gaps,
            known,
        )

    def _covered_days(self, series: _Series) -> list[date]:
        intervals = self._nautilus.get_intervals(
            series.nautilus_type, series.identifier
        )
        return _days_of(intervals)

    def _instrument_ids(self, stored: StoredType) -> list[InstrumentId]:
        folder = self._path / "data" / stored.directory
        if not folder.is_dir():
            return []
        names = self._nautilus.list_instruments(stored.nautilus_type)
        return [stored.instrument_id(each) for each in sorted(names)]

    def _records(self, series: _Series, window: Window) -> list[Any]:
        first, last = window.nanos
        return self._nautilus.query(
            series.nautilus_type, [series.identifier], first, last
        )


def _nanos(moment: datetime) -> int:
    return pd.Timestamp(moment).value


def _day(nanos: int) -> date:
    return datetime.fromtimestamp(nanos // 1_000_000_000, UTC).date()


def _ts_init(instrument: Any) -> int:
    return instrument.ts_init


def _clipped(intervals: Sequence[Interval], bounds: Interval) -> Iterator[Interval]:
    low, high = bounds
    for start, end in intervals:
        if _overlaps((start, end), bounds):
            yield max(start, low), min(end, high)


def _days_of(intervals: Iterable[Interval]) -> list[date]:
    return sorted(
        {each for start, end in intervals for each in days(_day(start), _day(end))}
    )


def _overlaps(one: Interval, other: Interval) -> bool:
    return one[0] <= other[1] and other[0] <= one[1]


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), UTC)
