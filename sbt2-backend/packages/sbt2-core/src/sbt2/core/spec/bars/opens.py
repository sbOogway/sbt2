from datetime import date
from pathlib import Path
from typing import Any, NamedTuple

import pandas as pd
from nautilus_trader.backtest import BacktestDataConfig
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    NautilusDataType,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.core.assets import QuoteJob
from sbt2.data import Catalog, Window

_MINUTE = 60_000_000_000
# Bar execution offers a quarter of a candle's volume at each of its four prices;
# an open point of the same size leaves the fills of a large order as they are.
_PRICES_PER_CANDLE = 4


def write_opens(job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
    """Write a trade at the open of each 1-minute candle of the instruments of
    ``job`` inside its window to a catalog in ``folder``, and return the data
    configs that stream them; none when there are none.

    Nautilus hands data at a time to the venue before it closes the bars that
    end then, so an order sent on a bar's close fills at the next candle's open.
    """
    target = ParquetDataCatalog(str(folder))
    writer = _Writer(job, target)
    target.write_instruments(writer.instruments)
    opened = [each.id for each in writer.instruments if writer.write(each)]
    if not opened:
        return []
    start, end = job.window
    return [
        BacktestDataConfig(
            catalog_path=str(folder),
            data_type=NautilusDataType.TradeTick,
            instrument_ids=opened,
            start_time=start,
            end_time=end,
        )
    ]


class _Writer:
    def __init__(self, job: QuoteJob, target: ParquetDataCatalog) -> None:
        self._catalog = Catalog(job.catalog)
        self._window = Window(*job.window)
        self._target = target
        self.instruments = list(self._catalog.instruments(job.instruments).values())

    def write(self, instrument: Any) -> bool:
        """Write one instrument's open points a day at a time; whether it has any."""
        found = False
        for day in self._window.days:
            points = self._points(instrument, day)
            if points:
                self._target.write_trade_ticks(
                    points, points[0].ts_event, points[-1].ts_event
                )
                found = True
        return found

    def _points(self, instrument: Any, day: date) -> list[TradeTick]:
        frame = self._catalog.frame(instrument.id, Bar, Window.of_days(day, day))
        first, last = self._window.nanos
        return [
            _open_point(instrument, each)
            for each in _opens(frame)
            if each.volume > 0 and first <= each.ts <= last
        ]


class _Open(NamedTuple):
    """The open of a candle: its time and price, and the candle's volume."""

    ts: int
    price: float
    volume: float


def _opens(candles: pd.DataFrame) -> list[_Open]:
    """The opens of the candles of the frame, each stamped 1 ns before its close."""
    times = pd.DatetimeIndex(candles.index).asi8 + 1 - _MINUTE
    return [
        _Open(*each)
        for each in zip(
            times.tolist(),
            candles["open"].tolist(),
            candles["volume"].tolist(),
            strict=True,
        )
    ]


def _open_point(instrument: Any, opened: _Open) -> TradeTick:
    return TradeTick(
        instrument.id,
        Price(opened.price, instrument.price_precision),
        _size(instrument, opened.volume / _PRICES_PER_CANDLE),
        AggressorSide.NO_AGGRESSOR,
        TradeId(str(opened.ts)),
        opened.ts,
        opened.ts,
    )


def _size(instrument: Any, volume: float) -> Quantity:
    size = Quantity(volume, instrument.size_precision)
    return max(size, instrument.size_increment)
