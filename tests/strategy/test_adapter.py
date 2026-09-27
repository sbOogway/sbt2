from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
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
    OrderSide,
    Price,
    Quantity,
    Symbol,
    TradeId,
    TradeTick,
    Venue,
)

from sbt2.strategy import AdapterConfig, importable_config

START = datetime(2024, 1, 1, tzinfo=UTC)
TRADE_START = START + timedelta(minutes=3)
LAST_BAR_MINUTE = 9
VENUE = Venue("BYBIT")
BTC = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
USDT = Currency.from_str("USDT")


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


def nanos(moment: datetime) -> int:
    return int(moment.timestamp()) * 1_000_000_000


def trades() -> list[TradeTick]:
    size = Quantity.from_str("10.000")
    price = Price.from_str("10000.0")
    return [
        TradeTick(BTC, price, size, AggressorSide.BUY, TradeId(str(n)), ts, ts)
        for n in range(2 * LAST_BAR_MINUTE + 1)
        for ts in [nanos(START + n * timedelta(seconds=30))]
    ]


def run(strategy: str, params: dict[str, Any] | None = None) -> BacktestEngine:
    config = AdapterConfig(strategy, [str(BTC)], params or {}, TRADE_START)
    engine = BacktestEngine(
        BacktestEngineConfig(logging=LoggerConfig(stdout_level=LogLevel.ERROR))
    )
    engine.add_venue(
        VENUE,
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money.from_str("10000 USDT")],
        default_leverage=Decimal(10),
        fee_model=FixedFeeModel(Money.from_str("0 USDT")),
    )
    engine.add_instrument(perpetual())
    engine.add_data(trades())
    engine.add_strategy_from_config(importable_config(config))
    engine.run()
    return engine


def orders(engine: BacktestEngine) -> list[Any]:
    return engine.cache.orders()


def net_position(engine: BacktestEngine) -> Decimal:
    return engine.portfolio.net_position(BTC)


def test_no_orders_before_the_trade_start() -> None:
    engine = run("toy_strategies:StepUp")

    first_order = min(order.ts_init for order in orders(engine))
    assert first_order == nanos(TRADE_START)


def test_targets_move_the_real_position_on_every_bar_after_the_start() -> None:
    engine = run("toy_strategies:StepUp", {"step": Decimal("0.250")})

    bars_after_start = LAST_BAR_MINUTE - 3 + 1
    assert len(orders(engine)) == bars_after_start
    assert net_position(engine) == bars_after_start * Decimal("0.250")


def test_quantities_below_the_size_increment_are_not_ordered() -> None:
    engine = run("toy_strategies:StepUp", {"step": "0.0004"})

    assert orders(engine) == []


def test_fills_reach_the_strategy() -> None:
    engine = run("toy_strategies:OneEquityUnitUntilFilled")

    assert [(order.side, str(order.quantity)) for order in orders(engine)] == [
        (OrderSide.BUY, "1.000"),
        (OrderSide.SELL, "1.000"),
    ]
    assert net_position(engine) == 0


def test_unknown_params_fail_when_the_adapter_is_built() -> None:
    with pytest.raises(RuntimeError, match="unknown parameters size"):
        run("toy_strategies:StepUp", {"size": 1})
