from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any, override

import pandas as pd
from nautilus_trader.backtest import BacktestDataConfig
from nautilus_trader.model import (
    Bar,
    BarSpecification,
    InstrumentId,
    MarkPriceUpdate,
    NautilusDataType,
    Price,
)
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.core.assets.conventions.quotes import QuoteConvention, QuoteJob
from sbt2.data import Catalog, Window

_CATALOG = "catalog"
_BARS = "bars"


class NoMarksError(LookupError):
    pass


class Marks(QuoteConvention):
    """The mark prices of an instrument: the ones the catalog holds, or, when the
    venue's ``marks`` setting is ``"bars"``, the close of each 1-minute bar, for
    a venue that serves no mark history."""

    @override
    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        if "quotes" in venue:
            raise ValueError("this asset class takes no quotes setting")
        if venue.get("marks", _CATALOG) not in (_CATALOG, _BARS):
            raise ValueError(
                f"the marks setting is {venue['marks']!r}, not {_CATALOG!r} "
                f"or {_BARS!r}"
            )
        return dict(venue)

    @override
    def unmakeable(self, inputs: Sequence[BarSpecification]) -> list[BarSpecification]:
        del inputs
        return []

    @override
    def source_types(self, kinds: set[type], venue: Mapping[str, Any]) -> set[type]:
        if not _from_bars(venue):
            return kinds
        return (kinds - {MarkPriceUpdate}) | {Bar}

    @override
    def priced_from(self, price_type: type, venue: Mapping[str, Any]) -> type:
        if price_type is MarkPriceUpdate and _from_bars(venue):
            return Bar
        return price_type

    @override
    def write(self, job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
        if not _from_bars(job.venue):
            return []
        start, end = job.window
        marked = _write_marks(job, ParquetDataCatalog(str(folder)))
        return [
            BacktestDataConfig(
                catalog_path=str(folder),
                data_type=NautilusDataType.MarkPriceUpdate,
                instrument_ids=marked,
                start_time=start,
                end_time=end,
            )
        ]


def _from_bars(venue: Mapping[str, Any]) -> bool:
    return venue.get("marks", _CATALOG) == _BARS


def _write_marks(job: QuoteJob, target: ParquetDataCatalog) -> list[InstrumentId]:
    """Write the marks of each instrument of ``job`` that has bars to ``target``,
    and return their ids."""
    writer = _Writer(job, target)
    instruments = writer.catalog.instruments(job.instruments)
    target.write_instruments(list(instruments.values()))
    marked = [
        each for each, instrument in instruments.items() if writer.write(instrument)
    ]
    if not marked:
        raise NoMarksError(_no_marks(job))
    return marked


class _Writer:
    def __init__(self, job: QuoteJob, target: ParquetDataCatalog) -> None:
        self.catalog = Catalog(job.catalog)
        self._window = Window(*job.window)
        self._target = target

    def write(self, instrument: Any) -> bool:
        """Write one instrument's marks a day at a time; whether it has any."""
        found = False
        for day in self._window.days:
            marks = self._marks(instrument, day)
            if marks:
                self._target.write_mark_price_updates(
                    marks, marks[0].ts_event, marks[-1].ts_event
                )
                found = True
        return found

    def _marks(self, instrument: Any, day: date) -> list[MarkPriceUpdate]:
        frame = self.catalog.frame(instrument.id, Bar, Window.of_days(day, day))
        times = pd.DatetimeIndex(frame.index).asi8.tolist()
        return [
            MarkPriceUpdate(
                instrument.id, Price(close, instrument.price_precision), ts, ts
            )
            for ts, close in zip(times, frame["close"].tolist(), strict=True)
        ]


def _no_marks(job: QuoteJob) -> str:
    ids = ", ".join(str(each) for each in job.instruments)
    return (
        f"no marks can be made for {ids} from {job.window[0]} to {job.window[1]}: "
        "the catalog lacks their 1-minute bars"
    )
