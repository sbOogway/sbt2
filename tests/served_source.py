"""A source serving raw files from memory, which records every file it is asked for.

Day files are JSON lists of timestamps, a record an hour; instrument snapshots are
nautilus's own instrument dicts.
"""

import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any

import nautilus_trader.model
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    CryptoPerpetual,
    CurrencyPair,
    FundingRateUpdate,
    InstrumentId,
    MarkPriceUpdate,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)

from sbt2.data.sources import (
    Gap,
    MissingAtSourceError,
    RawFile,
    Source,
    candle_type,
)

SYMBOL = "BTCUSDT"
INSTRUMENT_ID = InstrumentId.from_str(f"{SYMBOL}-LINEAR.BYBIT")
PRICE = "50000.0"
FUNDING_INTERVAL_MINUTES = 480
DATA_TYPES: tuple[type, ...] = (TradeTick, MarkPriceUpdate, FundingRateUpdate, Bar)
_HOUR = 3_600_000_000_000


class ServedSource(Source):
    def __init__(self, known_gaps: frozenset[Gap] = frozenset()) -> None:
        super().__init__(known_gaps)
        self.fetched: list[PurePosixPath] = []
        self._files: dict[PurePosixPath, bytes] = {}

    def serve(self, first: date, last: date, instrument: Any = None) -> None:
        """An instrument, the perpetual by default, and every day of each type
        from ``first`` to ``last``."""
        self.serve_instrument(instrument or perpetual())
        self.serve_days(first, last)

    def serve_days(self, first: date, last: date) -> None:
        for data_type in DATA_TYPES:
            for offset in range((last - first).days + 1):
                self.serve_day(data_type, first + timedelta(days=offset))

    def serve_day(self, data_type: type, day: date) -> None:
        start = _nanos(day)
        hours = [start + hour * _HOUR for hour in range(24)]
        self._files[self._day_path(data_type, day)] = json.dumps(hours).encode()

    def serve_instrument(self, instrument: Any) -> None:
        self._files[self._instrument_key()] = json.dumps(instrument.to_dict()).encode()

    def withdraw(self, data_type: type, day: date) -> None:
        del self._files[self._day_path(data_type, day)]

    @property
    def data_types(self) -> tuple[type, ...]:
        return DATA_TYPES

    def instrument_id(self, symbol: str) -> InstrumentId:
        return InstrumentId.from_str(f"{symbol}-LINEAR.BYBIT")

    def symbol(self, instrument_id: InstrumentId) -> str:
        return instrument_id.symbol.value.removesuffix("-LINEAR")

    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        path = self._day_path(data_type, day)
        return RawFile(path, partial(self._fetch, path))

    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        path = PurePosixPath("served", SYMBOL, "instrument", f"{taken_on}.json")
        return RawFile(path, partial(self._fetch, self._instrument_key()))

    def parse(self, path: Path, data_type: type, instrument: Any) -> Iterator[Any]:
        for ts in json.loads(path.read_text()):
            yield _RECORDS[data_type](instrument.id, ts)

    def parse_instrument(self, path: Path) -> Any:
        fields = json.loads(path.read_text())
        return getattr(nautilus_trader.model, fields["type"]).from_dict(fields)

    async def _fetch(self, path: PurePosixPath) -> bytes:
        self.fetched.append(path)
        try:
            return self._files[path]
        except KeyError:
            raise MissingAtSourceError(str(path)) from None

    def _day_path(self, data_type: type, day: date) -> PurePosixPath:
        return PurePosixPath("served", SYMBOL, data_type.__name__, f"{day}.json")

    def _instrument_key(self) -> PurePosixPath:
        return PurePosixPath("served", SYMBOL, "instrument")


def perpetual() -> CryptoPerpetual:
    return CryptoPerpetual(
        INSTRUMENT_ID,
        nautilus_trader.model.Symbol(SYMBOL),
        _currency("BTC"),
        _currency("USDT"),
        _currency("USDT"),
        False,
        1,
        3,
        Price.from_str("0.1"),
        Quantity.from_str("0.001"),
        0,
        0,
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
    )


def spot_pair() -> CurrencyPair:
    """A spot instrument under the perpetual's id."""
    return CurrencyPair(
        INSTRUMENT_ID,
        nautilus_trader.model.Symbol(SYMBOL),
        _currency("BTC"),
        _currency("USDT"),
        1,
        3,
        Price.from_str("0.1"),
        Quantity.from_str("0.001"),
        0,
        0,
    )


def _currency(code: str) -> Any:
    return nautilus_trader.model.Currency.from_str(code)


def _nanos(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * 10**9


def _trade(instrument_id: InstrumentId, ts: int) -> TradeTick:
    return TradeTick(
        instrument_id,
        Price.from_str(PRICE),
        Quantity.from_str("1.000"),
        AggressorSide.BUY,
        TradeId(str(ts)),
        ts,
        ts,
    )


def _mark(instrument_id: InstrumentId, ts: int) -> MarkPriceUpdate:
    return MarkPriceUpdate(instrument_id, Price.from_str(PRICE), ts, ts)


def _funding(instrument_id: InstrumentId, ts: int) -> FundingRateUpdate:
    return FundingRateUpdate(
        instrument_id, Decimal("0.0001"), ts, ts, interval=FUNDING_INTERVAL_MINUTES
    )


def _candle(instrument_id: InstrumentId, ts: int) -> Bar:
    price = Price.from_str(PRICE)
    volume = Quantity.from_str("1.000")
    return Bar(candle_type(instrument_id), price, price, price, price, volume, ts, ts)


_RECORDS = {
    Bar: _candle,
    TradeTick: _trade,
    MarkPriceUpdate: _mark,
    FundingRateUpdate: _funding,
}
