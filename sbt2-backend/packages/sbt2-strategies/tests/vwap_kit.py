"""1-minute candles of the Bybit perpetual and a run of a VWAP strategy on them."""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from bar_engine import BTC, MINUTE_NS, START, nanos, run_data
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.model import Bar, BarType, OrderSide, Price, Quantity

from sbt2.core.strategy import RunConfig

CANDLES = BarType.from_str(f"{BTC}-1-MINUTE-LAST-EXTERNAL")
DAY = 1440


def vwap_config(params: dict[str, Any]) -> RunConfig:
    """Trades ``BTC`` and takes it as the only feed of the VWAP."""
    return RunConfig(
        [str(BTC)],
        {"feeds": [str(BTC)], **params},
        START.isoformat(),
        aggregated_from="1-MINUTE-EXTERNAL",
    )


def candles(prices: Sequence[float]) -> list[Bar]:
    """One candle a minute, from ``START``, whose open, high, low and close are
    the price of its minute; the volume is the same in every minute."""
    return [_candle(minute, price) for minute, price in enumerate(prices)]


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


def _candle(minute: int, price: float) -> Bar:
    ts = nanos(START + timedelta(minutes=minute + 1)) - 1
    value = Price(price, 1)
    return Bar(CANDLES, value, value, value, value, Quantity(10, 3), ts, ts)
