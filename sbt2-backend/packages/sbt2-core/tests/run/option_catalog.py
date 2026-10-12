from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    AggressorSide,
    CryptoOption,
    Currency,
    InstrumentId,
    MarkPriceUpdate,
    OptionKind,
    Price,
    Quantity,
    Symbol,
    TradeId,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog

OPTION_ID = InstrumentId.from_str("BTC-1FEB24-50000-C.DERIBIT")
START = datetime(2024, 1, 1, tzinfo=UTC)
HOURS = 48
TRADE_PRICE = "0.0500"
FIRST_MARK = Decimal("0.0500")
MARK_STEP = Decimal("0.0010")
BTC = Currency.from_str("BTC")


def mark_at(hour: int) -> Decimal:
    return FIRST_MARK + MARK_STEP * hour


def build_option_catalog(path: Path) -> None:
    """Two days of one BTC option: a trade every minute at a flat price, a mark
    price every hour rising by ``MARK_STEP``."""
    path.mkdir(parents=True, exist_ok=True)
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([option()])
    first = _nanos(0)
    last = _nanos(HOURS) - 1
    minutes = range(first, last, 60_000_000_000)
    catalog.write_trade_ticks([_trade(ts) for ts in minutes], first, last)
    marks = [_mark(hour) for hour in range(HOURS)]
    catalog.write_mark_price_updates(marks, first, last)


def option() -> CryptoOption:
    return CryptoOption(
        OPTION_ID,
        Symbol(OPTION_ID.symbol.value),
        BTC,
        BTC,
        BTC,
        True,
        OptionKind.CALL,
        Price.from_str("50000"),
        _nanos(0),
        dt_to_unix_nanos(datetime(2024, 2, 1, tzinfo=UTC)),
        4,
        1,
        Price.from_str("0.0001"),
        Quantity.from_str("0.1"),
        0,
        0,
        multiplier=Quantity.from_str("1"),
        margin_init=Decimal(0),
        margin_maint=Decimal(0),
    )


def _nanos(hour: int) -> int:
    return dt_to_unix_nanos(START + timedelta(hours=hour))


def _trade(ts: int) -> TradeTick:
    return TradeTick(
        OPTION_ID,
        Price.from_str(TRADE_PRICE),
        Quantity.from_str("10.0"),
        AggressorSide.BUY,
        TradeId(str(ts)),
        ts,
        ts,
    )


def _mark(hour: int) -> MarkPriceUpdate:
    ts = _nanos(hour)
    return MarkPriceUpdate(OPTION_ID, Price(float(mark_at(hour)), 4), ts, ts)
