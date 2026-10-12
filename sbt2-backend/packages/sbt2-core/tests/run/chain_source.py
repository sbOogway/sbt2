"""Deribit's source serving two days of a small BTC chain from memory."""

import json
from datetime import UTC, date, datetime
from pathlib import PurePosixPath
from typing import Any, override

from sbt2.data.sources import MissingAtSourceError, RawFile
from sbt2.data.sources.deribit import DeribitSource

DELIVERY = 40_000.0
INDEX_PRICE = 45_000.0
DAYS = (date(2024, 1, 1), date(2024, 1, 2))
BEFORE = date(2023, 12, 31)
# name: (kind, expiry); each has the strike 45000
LISTING = {
    "BTC-2JAN24-45000-C": ("call", datetime(2024, 1, 2, 8, tzinfo=UTC)),
    "BTC-15FEB24-45000-P": ("put", datetime(2024, 2, 15, 8, tzinfo=UTC)),
    "BTC-28JUN24-45000-C": ("call", datetime(2024, 6, 28, 8, tzinfo=UTC)),
}


class ChainSource(DeribitSource):
    """The trades of ``DAYS`` for the ``LISTING``, their DVOL and the delivery
    price of 2 January. ``asked`` holds the raw paths the run asked for."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[PurePosixPath] = []

    @override
    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        path = super().day_file(symbol, data_type, day).path

        async def fetch() -> bytes:
            self.asked.append(path)
            return self._day(symbol, day)

        return RawFile(path, fetch)

    @override
    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        raw = super().instrument_snapshot(symbol, taken_on)
        if symbol != "BTC":
            return raw

        async def fetch() -> bytes:
            return json.dumps([_spec(name) for name in LISTING]).encode()

        return RawFile(raw.path, fetch)

    def serves(self, symbol: str) -> bool:
        del symbol
        return True

    def _day(self, symbol: str, day: date) -> bytes:
        if day not in DAYS or not self.serves(symbol):
            raise MissingAtSourceError(symbol)
        rows: Any = {
            "BTC": _trades(day),
            "BTC_DVOL": _dvol(day),
            "BTC_USD_DELIVERY": _delivery(day),
        }[symbol]
        if rows is None:
            raise MissingAtSourceError(symbol)
        return json.dumps(rows).encode()


class ChainSourceWithoutTrades(ChainSource):
    """The source with no trades, so no index price either."""

    @override
    def serves(self, symbol: str) -> bool:
        return symbol != "BTC"


def _ms(moment: datetime) -> int:
    return int(moment.timestamp() * 1000)


def _spec(name: str) -> dict[str, Any]:
    kind, expiry = LISTING[name]
    return {
        "instrument_name": name,
        "base_currency": "BTC",
        "quote_currency": "BTC",
        "settlement_currency": "BTC",
        "option_type": kind,
        "strike": 45000.0,
        "creation_timestamp": _ms(datetime(2023, 12, 1, tzinfo=UTC)),
        "expiration_timestamp": _ms(expiry),
        "tick_size": 0.0005,
        "min_trade_amount": 0.1,
        "contract_size": 1.0,
    }


def _trades(day: date) -> list[dict[str, Any]]:
    traded_at = datetime(day.year, day.month, day.day, 4, tzinfo=UTC)
    return [
        {
            "trade_id": f"{name}-{day}",
            "timestamp": _ms(traded_at),
            "price": 0.05,
            "mark_price": 0.05,
            "iv": 60.0,
            "instrument_name": name,
            "index_price": INDEX_PRICE,
            "direction": "buy",
            "amount": 1.0,
        }
        for name in LISTING
        if _ms(traded_at) < _ms(LISTING[name][1])
    ]


def _dvol(day: date) -> list[list[float]]:
    midnight = datetime(day.year, day.month, day.day, tzinfo=UTC)
    hour = 3_600_000
    return [[_ms(midnight) + each * hour, 50.0, 51.0, 49.0, 50.5] for each in range(24)]


def _delivery(day: date) -> list[dict[str, Any]] | None:
    if day != DAYS[1]:
        return None
    return [{"date": day.isoformat(), "delivery_price": DELIVERY}]


class ChainSourceWithLookBack(ChainSource):
    """The source that also serves the DVOL of the day before ``DAYS``."""

    @override
    def _day(self, symbol: str, day: date) -> bytes:
        if symbol == "BTC_DVOL" and day == BEFORE:
            return json.dumps(_dvol(day)).encode()
        return super()._day(symbol, day)
