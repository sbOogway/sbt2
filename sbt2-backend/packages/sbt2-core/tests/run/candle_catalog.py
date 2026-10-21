from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import Bar, MarkPriceUpdate, Price, Quantity
from nautilus_trader.persistence import ParquetDataCatalog
from synthetic_catalog import START

from sbt2.data import candle_type

MINUTE = 60_000_000_000

type Prices = tuple[float, float, float, float]


@dataclass(frozen=True)
class Candle:
    """The 1-minute candle that opens ``minute`` minutes after ``START``."""

    minute: int
    prices: Prices
    volume: float = 100.0

    @property
    def opens_at(self) -> int:
        return dt_to_unix_nanos(START) + self.minute * MINUTE

    def bar(self, instrument: Any) -> Bar:
        """The candle as the catalog holds it, stamped 1 ns before its close."""
        ts = self.opens_at + MINUTE - 1
        opened, high, low, close = (
            Price(each, instrument.price_precision) for each in self.prices
        )
        volume = Quantity(self.volume, instrument.size_precision)
        return Bar(candle_type(instrument.id), opened, high, low, close, volume, ts, ts)


def write_candles(path: Path, instrument: Any, candles: Sequence[Candle]) -> None:
    """The instrument and its ``candles`` in the catalog at ``path``."""
    path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([instrument])
    catalog.write_bars([each.bar(instrument) for each in candles])


def write_marks(path: Path, instrument: Any, candles: Sequence[Candle]) -> None:
    """A mark at each candle's close price, at the time the catalog holds it."""
    bars = [each.bar(instrument) for each in candles]
    marks = [
        MarkPriceUpdate(instrument.id, bar.close, bar.ts_event, bar.ts_event)
        for bar in bars
    ]
    ParquetDataCatalog(str(path)).write_mark_price_updates(
        marks, marks[0].ts_event, marks[-1].ts_event
    )
