from decimal import Decimal
from typing import Any

import pytest
from bar_engine import EQUITY, minute_bars, orders_of, perpetual, run
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.model import Money, OrderSide, OrderType, Price, Quantity
from nautilus_trader.risk import FixedRiskSizer

from sbt2.strategies.bracket_risk import (
    BracketParams,
    BracketRisk,
    Entry,
    plan_bracket,
)

PERIOD = 3
RISING = [10_000 + 10 * minute for minute in range(6)]
FALLING = [10_000 - 10 * minute for minute in range(6)]


@pytest.mark.unit
def test_entries_are_sized_with_the_fixed_risk_sizer() -> None:
    instrument = perpetual()
    equity = Money.from_str("10000 USDT")
    params = BracketParams(risk=Decimal("0.01"), stop=Decimal("0.005"))

    bracket = plan_bracket(
        instrument, Entry(OrderSide.BUY, Price.from_str("50000.0"), equity), params
    )

    expected = FixedRiskSizer(instrument).calculate(
        Price.from_str("50000.0"),
        Price.from_str("49750.0"),
        equity,
        Decimal("0.01"),
        unit_batch_size=Decimal("0.001"),
    )
    assert bracket.quantity == expected
    assert expected == Quantity.from_str("0.400")


def bracket_run(closes: list[int], balance: Money = EQUITY) -> BacktestEngine:
    return run(BracketRisk(minute_bars({"period": PERIOD})), closes, balance)


def exits(engine: BacktestEngine) -> tuple[Any, Any]:
    (stop_loss,) = orders_of(engine, OrderType.STOP_MARKET)
    (take_profit,) = orders_of(engine, OrderType.LIMIT)
    return stop_loss, take_profit


@pytest.mark.integration
def test_a_close_above_the_average_enters_a_long_bracket() -> None:
    engine = bracket_run(RISING)

    (entry,) = orders_of(engine, OrderType.MARKET)
    stop_loss, take_profit = exits(engine)
    close = Price.from_str(f"{RISING[PERIOD - 1]}.0")
    expected = plan_bracket(
        perpetual(), Entry(OrderSide.BUY, close, EQUITY), BracketParams(period=PERIOD)
    )
    assert entry.side == OrderSide.BUY
    assert entry.quantity == expected.quantity
    assert stop_loss.trigger_price == expected.stop_loss
    assert take_profit.price == expected.take_profit


@pytest.mark.integration
def test_a_close_below_the_average_enters_a_short_bracket() -> None:
    engine = bracket_run(FALLING)

    (entry,) = orders_of(engine, OrderType.MARKET)
    stop_loss, take_profit = exits(engine)
    close = Price.from_str(f"{FALLING[PERIOD - 1]}.0")
    assert entry.side == OrderSide.SELL
    assert stop_loss.trigger_price > close
    assert take_profit.price < close


@pytest.mark.integration
def test_no_new_bracket_while_a_position_or_its_exits_are_open() -> None:
    engine = bracket_run([10_000 + 2 * minute for minute in range(30)])

    assert len(orders_of(engine, OrderType.MARKET)) == 1


@pytest.mark.integration
def test_a_bracket_too_small_to_size_is_skipped() -> None:
    engine = bracket_run(RISING, Money.from_str("1 USDT"))

    assert engine.cache.orders() == []


@pytest.mark.integration
def test_a_close_on_the_average_enters_nothing() -> None:
    engine = bracket_run([10_000] * 6)

    assert engine.cache.orders() == []
