"""1-minute candles of the Bybit perpetual and a run of a VWAP strategy on them."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from bar_engine import BTC, MINUTE_NS, START, nanos, run_data
from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.common import LoggerConfig, LogLevel
from nautilus_trader.execution import FixedFeeModel
from nautilus_trader.model import (
    AccountType,
    Bar,
    BarType,
    CryptoPerpetual,
    Currency,
    InstrumentId,
    Money,
    OmsType,
    OrderSide,
    Price,
    Quantity,
    Symbol,
    Venue,
)

from sbt2.core.strategy import RunConfig

DAY = 1440
DERIBIT = InstrumentId.from_str("BTC-PERPETUAL.DERIBIT")
LINEAR_BARS = BarType.from_str(f"{BTC}-1-MINUTE-LAST-EXTERNAL")
INVERSE_BARS = BarType.from_str(f"{DERIBIT}-1-MINUTE-LAST-EXTERNAL")


def vwap_config(params: dict[str, Any]) -> RunConfig:
    """Trades ``BTC`` and takes it as the only feed of the VWAP."""
    return RunConfig(
        [str(BTC)],
        {"feeds": [str(BTC)], **params},
        START.isoformat(),
        aggregated_from="1-MINUTE-EXTERNAL",
    )


def inverse_config(params: dict[str, Any]) -> RunConfig:
    """Trades the Deribit perpetual and takes it as the only feed."""
    return RunConfig(
        [str(DERIBIT)],
        {"feeds": [str(DERIBIT)], **params},
        START.isoformat(),
        aggregated_from="1-MINUTE-EXTERNAL",
    )


def run_inverse(strategy: Any, prices: Sequence[float]) -> BacktestEngine:
    """Runs ``strategy`` on Deribit's inverse perpetual with 1 BTC."""
    engine = BacktestEngine(
        BacktestEngineConfig(logging=LoggerConfig(stdout_level=LogLevel.ERROR))
    )
    engine.add_venue(
        Venue("DERIBIT"),
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money.from_str("1 BTC")],
        default_leverage=Decimal(10),
        fee_model=FixedFeeModel(Money.from_str("0 BTC")),
    )
    engine.add_instrument(_inverse_perpetual())
    engine.add_data(inverse_candles(prices))
    engine.add_strategy(strategy)
    engine.run(end=nanos(START + timedelta(minutes=len(prices))))
    return engine


def _inverse_perpetual() -> CryptoPerpetual:
    return CryptoPerpetual(
        DERIBIT,
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


def candles(prices: Sequence[float]) -> list[Bar]:
    """One candle a minute, from ``START``, whose open, high, low and close are
    the price of its minute; the volume is the same in every minute."""
    return _series(prices, _Series(LINEAR_BARS, Quantity(10, 3)))


def inverse_candles(prices: Sequence[float]) -> list[Bar]:
    """The same for Deribit's perpetual, whose volume is in USD."""
    return _series(prices, _Series(INVERSE_BARS, Quantity(1_000_000, 0)))


def run_candles(strategy: Any, prices: Sequence[float]) -> BacktestEngine:
    return run_data(strategy, candles(prices))


def day(*segments: tuple[int, float]) -> list[float]:
    """A day of prices: each segment is a number of minutes at one price, the
    last price lasting to the end of the day."""
    prices = [price for minutes, price in segments for _ in range(minutes)]
    return prices + [prices[-1]] * (DAY - len(prices))


def orders_sent(engine: BacktestEngine) -> list[tuple[OrderSide, int]]:
    """The side of each order and the minute of the run at which its bar closed."""
    orders = sorted(engine.cache.orders(), key=lambda order: order.ts_init)
    return [
        (order.side, (order.ts_init + 1 - nanos(START)) // MINUTE_NS)
        for order in orders
    ]


@dataclass(frozen=True)
class _Series:
    bar_type: BarType
    volume: Quantity


def _series(prices: Sequence[float], series: _Series) -> list[Bar]:
    return [_candle(minute, price, series) for minute, price in enumerate(prices)]


def _candle(minute: int, price: float, series: _Series) -> Bar:
    ts = nanos(START + timedelta(minutes=minute + 1)) - 1
    value = Price(price, 1)
    return Bar(series.bar_type, value, value, value, value, series.volume, ts, ts)
