"""A Bybit perpetual and an engine that closes one 1-minute bar per price."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.common import LoggerConfig, LogLevel
from nautilus_trader.execution import FixedFeeModel
from nautilus_trader.model import (
    AccountType,
    AggressorSide,
    CryptoPerpetual,
    Currency,
    InstrumentId,
    Money,
    OmsType,
    OrderType,
    Price,
    Quantity,
    Symbol,
    TradeId,
    TradeTick,
    Venue,
)
from nautilus_trader.trading import Strategy as NautilusStrategy

from sbt2.core.strategy import RunConfig

START = datetime(2024, 1, 1, tzinfo=UTC)
BTC = InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")
USDT = Currency.from_str("USDT")
EQUITY = Money.from_str("10000 USDT")


def perpetual() -> CryptoPerpetual:
    return CryptoPerpetual(
        BTC,
        Symbol("BTCUSDT"),
        Currency.from_str("BTC"),
        USDT,
        USDT,
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


def minute_bars(params: dict[str, Any]) -> RunConfig:
    """Trades ``BTC`` on 1-minute bars from the first one on."""
    return RunConfig([str(BTC)], {"bar": "1-MINUTE-LAST", **params}, START.isoformat())


def run(
    strategy: NautilusStrategy, closes: list[int], balance: Money = EQUITY
) -> BacktestEngine:
    """Runs ``strategy`` on one trade a minute, so the bar of minute ``k``
    closes at ``closes[k]``."""
    engine = BacktestEngine(
        BacktestEngineConfig(logging=LoggerConfig(stdout_level=LogLevel.ERROR))
    )
    engine.add_venue(
        Venue("BYBIT"),
        OmsType.NETTING,
        AccountType.MARGIN,
        [balance],
        default_leverage=Decimal(10),
        fee_model=FixedFeeModel(Money.from_str("0 USDT")),
    )
    engine.add_instrument(perpetual())
    engine.add_data(_trades(closes))
    engine.add_strategy(strategy)
    engine.run(end=_nanos(START + timedelta(minutes=len(closes))))
    return engine


def orders_of(engine: BacktestEngine, kind: OrderType) -> list[Any]:
    return [order for order in _by_time(engine) if order.order_type == kind]


def _by_time(engine: BacktestEngine) -> list[Any]:
    return sorted(engine.cache.orders(), key=lambda order: order.ts_init)


def _trades(closes: list[int]) -> list[TradeTick]:
    size = Quantity.from_str("10.000")
    return [
        TradeTick(
            BTC,
            Price.from_str(f"{price}.0"),
            size,
            AggressorSide.BUY,
            TradeId(str(minute)),
            ts,
            ts,
        )
        for minute, price in enumerate(closes)
        for ts in [_nanos(START + timedelta(minutes=minute, seconds=30))]
    ]


def _nanos(moment: datetime) -> int:
    return int(moment.timestamp()) * 1_000_000_000
