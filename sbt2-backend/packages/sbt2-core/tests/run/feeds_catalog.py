from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from deribit_perpetual_catalog import build_catalog as build_deribit_catalog
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    Bar,
    CryptoPerpetual,
    Currency,
    InstrumentId,
    Price,
    Quantity,
    Symbol,
)
from nautilus_trader.persistence import ParquetDataCatalog
from synthetic_catalog import START

from sbt2.data import candle_type

BINANCE = InstrumentId.from_str("BTCUSDT-PERP.BINANCE")
OKX = InstrumentId.from_str("BTC-USDT-SWAP.OKX")
BINANCE_VOLUME = 2
OKX_CONTRACTS = 300
OKX_COIN_PER_CONTRACT = Decimal("0.01")
_VOLUMES = {BINANCE: BINANCE_VOLUME, OKX: OKX_CONTRACTS}
_MINUTE = 60_000_000_000
_DAY = 1440


def price_of(feed: InstrumentId, minute: int) -> float:
    """The price of every field of the feed's candle that opens ``minute``
    minutes after the start."""
    base = 50_000 if feed == BINANCE else 50_100
    return base + minute % 10


def build_catalog(path: Path, okx_days: int = 2) -> None:
    """The Deribit perpetual of two days, and the 1-minute candles of the same
    days from Binance and, for ``okx_days`` of them, from OKX."""
    build_deribit_catalog(path)
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([_perpetual(BINANCE, "1"), _perpetual(OKX, "0.01")])
    for day in range(2):
        _write_day(catalog, BINANCE, day)
        if day < okx_days:
            _write_day(catalog, OKX, day)


def _write_day(catalog: ParquetDataCatalog, feed: InstrumentId, day: int) -> None:
    first = dt_to_unix_nanos(START + timedelta(days=day))
    bars = [_bar(feed, day * _DAY + minute) for minute in range(_DAY)]
    catalog.write_bars(bars, first, first + _DAY * _MINUTE - 1)


def _bar(feed: InstrumentId, minute: int) -> Bar:
    """Stamped 1 ns before its close, as the catalog holds the candles."""
    ts = dt_to_unix_nanos(START) + (minute + 1) * _MINUTE - 1
    price = Price(price_of(feed, minute), 1)
    volume = Quantity(_VOLUMES[feed], 0)
    return Bar(candle_type(feed), price, price, price, price, volume, ts, ts)


def _perpetual(feed: InstrumentId, multiplier: str) -> CryptoPerpetual:
    return CryptoPerpetual(
        feed,
        Symbol(feed.symbol.value),
        Currency.from_str("BTC"),
        Currency.from_str("USDT"),
        Currency.from_str("USDT"),
        False,
        1,
        0,
        Price.from_str("0.1"),
        Quantity.from_str("1"),
        0,
        0,
        multiplier=Quantity.from_str(multiplier),
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
    )
