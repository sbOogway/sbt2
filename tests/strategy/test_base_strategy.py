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
    Bar,
    BarType,
    CryptoPerpetual,
    Currency,
    InstrumentId,
    Money,
    OmsType,
    Price,
    Quantity,
    Symbol,
    TradeId,
    TradeTick,
    Venue,
)
from nautilus_trader.trading import Strategy as NautilusStrategy
from toy_strategies import BuyEveryBar, CountWarmupBars, FailOnSecondBar, RecordBars

from sbt2.strategy import RunConfig, StrategyRun, build_strategy, importable_config

START = datetime(2024, 1, 1, tzinfo=UTC)
TRADE_START = START + timedelta(minutes=3)
LAST_BAR_MINUTE = 9
BARS_FROM_TRADE_START = LAST_BAR_MINUTE - 3 + 1
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


def candles(days: int) -> list[Bar]:
    """1-minute candles stamped 1 ns before their close; minute ``k`` trades at k."""
    candle_type = BarType.from_str(f"{BTC}-1-MINUTE-LAST-EXTERNAL")
    volume = Quantity.from_str("1.000")
    bars = []
    for minute in range(days * 24 * 60):
        price = Price.from_str(f"{10000 + minute}.0")
        ts = nanos(START + (minute + 1) * timedelta(minutes=1)) - 1
        bars.append(Bar(candle_type, price, price, price, price, volume, ts, ts))
    return bars


def engine_with_trades() -> BacktestEngine:
    engine = empty_engine()
    engine.add_data(trades())
    return engine


def empty_engine() -> BacktestEngine:
    engine = BacktestEngine(
        BacktestEngineConfig(logging=LoggerConfig(stdout_level=LogLevel.ERROR))
    )
    engine.add_venue(
        Venue("BYBIT"),
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money.from_str("10000 USDT")],
        default_leverage=Decimal(10),
        fee_model=FixedFeeModel(Money.from_str("0 USDT")),
    )
    engine.add_instrument(perpetual())
    return engine


def run_from_path(
    strategy: str, params: dict[str, Any] | None = None
) -> BacktestEngine:
    engine = engine_with_trades()
    run = StrategyRun(strategy, [BTC], params or {}, TRADE_START)
    engine.add_strategy_from_config(importable_config(run))
    engine.run()
    return engine


def run_instance(strategy: NautilusStrategy) -> None:
    engine = engine_with_trades()
    engine.add_strategy(strategy)
    engine.run()


@pytest.mark.integration
def test_orders_submitted_during_warmup_are_dropped() -> None:
    engine = run_from_path("toy_strategies:BuyEveryBar")

    first_order = min(order.ts_init for order in engine.cache.orders())
    assert first_order == nanos(TRADE_START)
    assert len(engine.cache.orders()) == BARS_FROM_TRADE_START


@pytest.mark.integration
def test_params_survive_the_importable_config() -> None:
    engine = run_from_path("toy_strategies:BuyEveryBar", {"step": Decimal("0.250")})

    expected = BARS_FROM_TRADE_START * Decimal("0.250")
    assert engine.portfolio.net_position(BTC) == expected


@pytest.mark.integration
def test_declared_bars_are_subscribed_and_warmup_ends_at_the_trade_start() -> None:
    strategy = CountWarmupBars(RunConfig([str(BTC)], {}, TRADE_START.isoformat()))

    run_instance(strategy)

    assert (strategy.warmup_bars, strategy.trading_bars) == (3, BARS_FROM_TRADE_START)


@pytest.mark.unit
def test_declared_bars_are_aggregated_internally_for_every_instrument() -> None:
    strategy = CountWarmupBars(RunConfig([str(BTC)], {}, TRADE_START.isoformat()))

    assert strategy.bar_types() == [
        BarType.from_str("BTCUSDT-PERP.BYBIT-1-MINUTE-LAST-INTERNAL")
    ]


@pytest.mark.integration
def test_a_candle_run_subscribes_bars_aggregated_from_candles() -> None:
    config = RunConfig([str(BTC)], {}, START.isoformat(), "1-MINUTE-EXTERNAL")
    strategy = RecordBars(config)
    engine = empty_engine()
    engine.add_strategy(strategy)

    engine.run(start=nanos(START), end=nanos(START))

    assert strategy.subscribed == [
        BarType.from_str("BTCUSDT-PERP.BYBIT-1-HOUR-LAST-INTERNAL@1-MINUTE-EXTERNAL")
    ]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("bar", "closes", "first"),
    [
        ("1-HOUR-LAST", 48, ("10000.0", "10059.0", "10000.0", "10059.0", "60.000")),
        ("1-DAY-LAST", 2, ("10000.0", "11439.0", "10000.0", "11439.0", "1440.000")),
    ],
)
def test_bars_built_from_candles_arrive_under_the_types_the_strategy_is_given(
    bar: str, closes: int, first: tuple[str, ...]
) -> None:
    config = RunConfig([str(BTC)], {"bar": bar}, START.isoformat(), "1-MINUTE-EXTERNAL")
    strategy = RecordBars(config)
    engine = empty_engine()
    engine.add_data(candles(days=2))
    engine.add_strategy(strategy)

    engine.run(end=nanos(START + timedelta(days=2)))

    assert len(strategy.bars) == closes
    assert {each.bar_type for each in strategy.bars} == set(strategy.bar_types())
    head = strategy.bars[0]
    assert (
        tuple(map(str, (head.open, head.high, head.low, head.close, head.volume)))
        == first
    )
    assert strategy.bars[-1].ts_event == nanos(START + timedelta(days=2))


@pytest.mark.integration
def test_unknown_params_fail_when_the_strategy_is_built() -> None:
    with pytest.raises(RuntimeError, match="unknown parameters size"):
        run_from_path("toy_strategies:BuyEveryBar", {"size": 1})


@pytest.mark.unit
def test_build_strategy_imports_and_configures_the_run() -> None:
    run = StrategyRun("toy_strategies:BuyEveryBar", [BTC], {"lookback": 5}, START)

    strategy = build_strategy(run)

    assert isinstance(strategy, BuyEveryBar)
    assert strategy.params.lookback == 5


@pytest.mark.integration
def test_a_handler_exception_is_kept_as_the_failure() -> None:
    strategy = FailOnSecondBar(RunConfig([str(BTC)], {}, START.isoformat()))

    run_instance(strategy)

    assert isinstance(strategy.failure, ValueError)
    assert str(strategy.failure) == "failed on bar 2"


@pytest.mark.integration
def test_a_clean_run_has_no_failure() -> None:
    strategy = CountWarmupBars(RunConfig([str(BTC)], {}, TRADE_START.isoformat()))

    run_instance(strategy)

    assert strategy.failure is None
