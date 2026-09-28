import hashlib
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import cached_property
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import (
    InstrumentId,
    NautilusDataType,
)
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.data.days import days
from sbt2.sources import Gap

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
class _Series:
    instrument_id: InstrumentId
    data_type: type

    @property
    def nautilus_type(self) -> NautilusDataType:
        return _nautilus_type(self.data_type)

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

    def fingerprint(self, selection: Selection) -> str:
        """A hash of the names and sizes of the selected files in the window,
        and of the selection's instruments."""
        digest = hashlib.sha256()
        for line in self._file_lines(selection):
            digest.update(f"{line}\n".encode())
        for instrument in self.instruments(selection.instrument_ids).values():
            digest.update(_canonical(instrument).encode())
        return digest.hexdigest()

    @cached_property
    def _nautilus(self) -> ParquetDataCatalog:
        return ParquetDataCatalog(str(self._path))

    def _coverage(
        self, series: _Series, window: Window, known_gaps: frozenset[Gap]
    ) -> Coverage:
        first, last = window.nanos
        intervals = self._nautilus.get_missing_intervals_for_request(
            first, last, series.nautilus_type, str(series.instrument_id)
        )
        missing, known = series.split(
            _days_of(_clipped(intervals, window.nanos)), known_gaps
        )
        return Coverage(series.instrument_id, series.data_type, missing, known)

    def _file_lines(self, selection: Selection) -> list[str]:
        return sorted(
            f"{name} {(self._path / name).stat().st_size}"
            for instrument_id in selection.instrument_ids
            for data_type in selection.data_types
            for name in self._files(_Series(instrument_id, data_type))
            if _overlaps(_file_bounds(name), selection.window.nanos)
        )

    def _files(self, series: _Series) -> list[str]:
        return self._nautilus.list_parquet_files(
            series.nautilus_type, str(series.instrument_id)
        )


def _nanos(moment: datetime) -> int:
    return pd.Timestamp(moment).value


def _day(nanos: int) -> date:
    return datetime.fromtimestamp(nanos // 1_000_000_000, UTC).date()


def _nautilus_type(data_type: type) -> NautilusDataType:
    return getattr(NautilusDataType, data_type.__name__)


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


def _file_bounds(name: str) -> Interval:
    """The bounds nautilus encodes in a data file's name."""
    first, last = Path(name).stem.split("_")
    return _file_timestamp(first), _file_timestamp(last)


def _file_timestamp(text: str) -> int:
    moment, nanos = text[:19], text[20:29]
    seconds = datetime.strptime(moment, "%Y-%m-%dT%H-%M-%S").replace(tzinfo=UTC)
    return int(seconds.timestamp()) * 1_000_000_000 + int(nanos)


def _canonical(instrument: Any) -> str:
    return json.dumps(instrument.to_dict(), sort_keys=True, default=str)
