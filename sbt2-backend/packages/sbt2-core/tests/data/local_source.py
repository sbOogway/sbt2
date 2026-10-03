"""A source whose raw day files are JSON lists of timestamps, written by the tests."""

import json
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any

from nautilus_trader.model import (
    AggressorSide,
    Bar,
    CryptoPerpetual,
    Currency,
    FundingRateUpdate,
    InstrumentId,
    MarkPriceUpdate,
    Price,
    Quantity,
    Symbol,
    TradeId,
    TradeTick,
)

from sbt2.core.data.sources import RawFile, Source, candle_type

SYMBOL = "BTCUSDT"
INSTRUMENT_ID = InstrumentId.from_str(f"{SYMBOL}-PERP.LOCAL")
CANDLE_TYPE = candle_type(INSTRUMENT_ID)
PRICE = "50000.0"
FUNDING_RATE = Decimal("0.0001")
FUNDING_INTERVAL_MINUTES = 480


class LocalSource(Source):
    @property
    def data_types(self) -> tuple[type, ...]:
        return (TradeTick, MarkPriceUpdate, FundingRateUpdate, Bar)

    def instrument_id(self, symbol: str) -> InstrumentId:
        return InstrumentId.from_str(f"{symbol}-PERP.LOCAL")

    def symbol(self, instrument_id: InstrumentId) -> str:
        return instrument_id.symbol.value.removesuffix("-PERP")

    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        path = PurePosixPath("local", symbol, data_type.__name__, f"{day}.json")
        return RawFile(path, "unused")

    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        name = f"{symbol}{taken_on.isoformat()}.json"
        return RawFile(PurePosixPath("local", symbol, "instrument", name), "unused")

    def parse(self, path: Path, data_type: type, instrument: Any) -> Iterator[Any]:
        for ts in json.loads(path.read_text()):
            yield _RECORDS[data_type](instrument.id, ts)

    def parse_instrument(self, path: Path) -> Any:
        return CryptoPerpetual.from_dict(json.loads(path.read_text()))


def write_snapshot(raw: Path, taken_on: date, margin_init: str = "0.01") -> Path:
    fields = {
        **perpetual().to_dict(),
        "margin_init": margin_init,
        "ts_event": _nanos(taken_on),
        "ts_init": _nanos(taken_on),
    }
    return _write(raw, LocalSource().instrument_snapshot(SYMBOL, taken_on), fields)


class RawFolder:
    def __init__(self, path: Path) -> None:
        self.path = path

    def write_day(self, data_type: type, day: date, timestamps: Iterable[int]) -> Path:
        raw_file = LocalSource().day_file(SYMBOL, data_type, day)
        return _write(self.path, raw_file, list(timestamps))


def perpetual() -> CryptoPerpetual:
    return CryptoPerpetual(
        INSTRUMENT_ID,
        Symbol(SYMBOL),
        Currency.from_str("BTC"),
        Currency.from_str("USDT"),
        Currency.from_str("USDT"),
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


def start_of(day: date) -> int:
    return _nanos(day)


def _nanos(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()) * 10**9


def _write(raw: Path, raw_file: RawFile, content: Any) -> Path:
    path = raw / raw_file.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(content))
    return path


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
        instrument_id, FUNDING_RATE, ts, ts, interval=FUNDING_INTERVAL_MINUTES
    )


def _candle(instrument_id: InstrumentId, ts: int) -> Bar:
    price = Price.from_str(PRICE)
    volume = Quantity.from_str("1.000")
    return Bar(candle_type(instrument_id), price, price, price, price, volume, ts, ts)


_RECORDS = {
    TradeTick: _trade,
    MarkPriceUpdate: _mark,
    FundingRateUpdate: _funding,
    Bar: _candle,
}
