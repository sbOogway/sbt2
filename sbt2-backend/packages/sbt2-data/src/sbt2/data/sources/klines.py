import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar, override

import pandas as pd
from nautilus_trader.model import (
    Bar,
    CryptoPerpetual,
    Currency,
    InstrumentId,
    Price,
    Quantity,
    Symbol,
)

from sbt2.data.sources.base import (
    Fetch,
    RawFile,
    Source,
    UnsupportedDataTypeError,
    candle_type,
)

_NANOS_PER_MILLI = 1_000_000
_NANOS_PER_MINUTE = 60_000_000_000
_CANDLES = "candles"


@dataclass(frozen=True)
class Kline:
    """One 1-minute kline as an exchange gives it: the open time in milliseconds,
    and the prices and the volume as decimal text."""

    open_ms: int
    open: str
    high: str
    low: str
    close: str
    volume: str


@dataclass(frozen=True)
class PerpetualSpec:
    """What a perpetual instrument needs, in the exchange's own decimal text.

    ``multiplier`` is the base-coin size of one volume unit of the klines.
    """

    base: str
    quote: str
    settlement: str
    price_increment: str
    size_increment: str
    multiplier: str
    margin_init: Decimal
    margin_maint: Decimal
    ts_event: int
    is_inverse: bool = False


class Pacer:
    """Spaces the calls of one exchange's API at least ``pause`` seconds apart."""

    def __init__(self, pause: float) -> None:
        self._pause = pause
        self._next = 0.0

    async def wait(self) -> None:
        now = time.monotonic()
        start = max(now, self._next)
        self._next = start + self._pause
        await asyncio.sleep(start - now)


def utc_day_window(day: date) -> tuple[datetime, datetime]:
    """The UTC day as its first instant and the first instant of the next."""
    start = datetime(day.year, day.month, day.day, tzinfo=UTC)
    return start, start + timedelta(days=1)


def bars(rows: Iterable[Kline], instrument: Any) -> Iterator[Bar]:
    """The klines in time order, each stamped 1 ns before its close, as Bybit's
    candles are, so a bar is known only once its minute is over and a day's last
    bar stays inside the day's catalog file bounds."""
    bar_type = candle_type(instrument.id)
    for row in sorted(rows, key=lambda each: each.open_ms):
        ts = row.open_ms * _NANOS_PER_MILLI + _NANOS_PER_MINUTE - 1
        yield Bar(
            bar_type,
            _price(row.open, instrument),
            _price(row.high, instrument),
            _price(row.low, instrument),
            _price(row.close, instrument),
            Quantity(float(row.volume), instrument.size_precision),
            ts,
            ts,
        )


class KlineSource(Source, ABC):
    """A source of one exchange's 1-minute perpetual klines: one raw file per
    symbol and UTC day, and the instrument's spec as a snapshot.

    A subclass names its exchange and says where each file comes from and how
    to read it. ``id_suffix`` ends the nautilus symbol of its instruments.
    """

    venue: ClassVar[str]
    folder: ClassVar[str]
    extension: ClassVar[str] = "json"
    id_suffix: ClassVar[str] = ""

    @property
    @override
    def data_types(self) -> tuple[type, ...]:
        return (Bar,)

    @override
    def instrument_id(self, symbol: str) -> InstrumentId:
        return InstrumentId.from_str(f"{symbol}{self.id_suffix}.{self.venue}")

    @override
    def symbol(self, instrument_id: InstrumentId) -> str:
        symbol = instrument_id.symbol.value.removesuffix(self.id_suffix)
        if self.instrument_id(symbol) != instrument_id:
            raise ValueError(f"{instrument_id} is not a {self.name} instrument")
        return symbol

    @override
    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        if data_type is not Bar:
            raise UnsupportedDataTypeError(
                f"{self.name} serves candles, not {data_type.__name__}"
            )
        name = f"{symbol}{day.isoformat()}.{self.extension}"
        return RawFile(
            PurePosixPath(self.folder, symbol, _CANDLES, name),
            self._day_origin(symbol, day),
        )

    @override
    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        name = f"{symbol}{taken_on.isoformat()}.json"
        return RawFile(
            PurePosixPath(self.folder, symbol, "instrument", name),
            partial(self._snapshot, symbol),
        )

    @override
    def parse(self, path: Path, data_type: type, instrument: Any) -> Iterator[Any]:
        return bars(self._klines(path), instrument)

    @override
    def parse_instruments(self, path: Path) -> Mapping[InstrumentId, Any]:
        symbol = path.stem[: -len("YYYY-MM-DD")]
        ts_init = _snapshot_day_nanos(path)
        instrument = self._instrument(path, self.instrument_id(symbol), ts_init)
        return {instrument.id: instrument}

    @override
    def _listed_data_type(self, name: str) -> type:
        if name != _CANDLES:
            raise UnsupportedDataTypeError(
                f"{self.name} lists no data type {name}; it lists {_CANDLES}"
            )
        return Bar

    @abstractmethod
    def _day_origin(self, symbol: str, day: date) -> str | Fetch:
        """Where the raw file of the UTC day comes from."""

    @abstractmethod
    async def _snapshot(self, symbol: str) -> bytes:
        """The exchange's spec of the symbol as JSON."""

    @abstractmethod
    def _klines(self, path: Path) -> Iterator[Kline]:
        """The klines of one raw day file."""

    @abstractmethod
    def _instrument(
        self, snapshot: Path, instrument_id: InstrumentId, ts_init: int
    ) -> CryptoPerpetual:
        """The perpetual a snapshot describes."""


def _price(text: str, instrument: Any) -> Price:
    return Price(float(text), instrument.price_precision)


def perpetual_of(
    instrument_id: InstrumentId, spec: PerpetualSpec, ts_init: int
) -> CryptoPerpetual:
    """The perpetual of an exchange's spec."""
    price_precision = _decimals(spec.price_increment)
    size_precision = _decimals(spec.size_increment)
    return CryptoPerpetual(
        instrument_id,
        Symbol(instrument_id.symbol.value),
        Currency.from_str(spec.base),
        Currency.from_str(spec.quote),
        Currency.from_str(spec.settlement),
        spec.is_inverse,
        price_precision,
        size_precision,
        Price(float(spec.price_increment), price_precision),
        Quantity(float(spec.size_increment), size_precision),
        spec.ts_event,
        ts_init,
        multiplier=Quantity(float(spec.multiplier), _decimals(spec.multiplier)),
        margin_init=spec.margin_init,
        margin_maint=spec.margin_maint,
    )


def _decimals(text: str) -> int:
    """The decimal places of a number as the exchange writes it."""
    return len(text.partition(".")[2])


def _snapshot_day_nanos(path: Path) -> int:
    taken_on = date.fromisoformat(path.stem[-len("YYYY-MM-DD") :])
    return pd.Timestamp(taken_on, tz="UTC").value
