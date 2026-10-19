from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    Bar,
    BarType,
    CryptoPerpetual,
    Currency,
    FundingRateUpdate,
    InstrumentId,
    Price,
    Quantity,
    Symbol,
)
from nautilus_trader.persistence import ParquetDataCatalog
from synthetic_catalog import START, write_funding

from sbt2.data import candle_type

INSTRUMENT_ID = InstrumentId.from_str("BTC-PERPETUAL.DERIBIT")
HOURS = 48
FIRST_PRICE = 50_000
HOURLY_RISE = 100
FUNDING_RATE = Decimal("0.0001")
_MINUTE = 60_000_000_000
_HOUR = 60 * _MINUTE


def price_in_hour(hour: int) -> int:
    """The price of every minute of the hour: the open, high, low and close."""
    return FIRST_PRICE + HOURLY_RISE * hour


def build_catalog(path: Path) -> None:
    """Two days of Deribit's inverse BTC perpetual: 1-minute bars and no mark
    prices, funding every hour."""
    path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([perpetual()])
    for day in range(HOURS // 24):
        first = dt_to_unix_nanos(START + timedelta(days=day))
        last = first + 24 * _HOUR - 1
        catalog.write_bars(_bars(day), first, last)
        write_funding(path, _fundings(day), (first, last))


def perpetual() -> CryptoPerpetual:
    return CryptoPerpetual(
        INSTRUMENT_ID,
        Symbol("BTC-PERPETUAL"),
        Currency.from_str("BTC"),
        Currency.from_str("USD"),
        Currency.from_str("BTC"),
        True,
        1,
        0,
        Price.from_str("0.5"),
        Quantity.from_str("10"),
        0,
        0,
        margin_init=Decimal("0.02"),
        margin_maint=Decimal("0.0133"),
    )


def _bars(day: int) -> list[Bar]:
    """Each minute's bar is stamped 1 ns before its close, as the catalog holds them."""
    first = dt_to_unix_nanos(START + timedelta(days=day))
    bar_type = candle_type(INSTRUMENT_ID)
    return [
        _bar(bar_type, first + minute * _MINUTE, price_in_hour(day * 24 + minute // 60))
        for minute in range(24 * 60)
    ]


def _bar(bar_type: BarType, start: int, price: int) -> Bar:
    ts = start + _MINUTE - 1
    text = f"{price}.0"
    return Bar(
        bar_type,
        Price.from_str(text),
        Price.from_str(text),
        Price.from_str(text),
        Price.from_str(text),
        Quantity.from_str("1000000000"),
        ts,
        ts,
    )


def _fundings(day: int) -> list[FundingRateUpdate]:
    return [
        FundingRateUpdate(INSTRUMENT_ID, FUNDING_RATE, ts, ts, interval=60)
        for hour in range(24)
        for ts in [dt_to_unix_nanos(START + timedelta(days=day, hours=hour))]
    ]
