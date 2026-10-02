from datetime import timedelta
from typing import Any

import pytest
from bar_engine import BTC, minute_bars, orders_of, run
from nautilus_trader.model import BarSpecification, OrderSide, OrderType, Quantity

from sbt2.core.strategy import import_strategy, resolve_params
from sbt2.strategies.ma_cross import MovingAverageCross

PATH = "sbt2.strategies.ma_cross:MovingAverageCross"
AVERAGES = {"fast": 2, "slow": 4}
QUANTITY = Quantity.from_str("0.100")
RISING = [10_000 + 10 * minute for minute in range(8)]


@pytest.mark.unit
def test_the_crossover_warms_up_for_its_slow_average() -> None:
    strategy = import_strategy(PATH)
    params = resolve_params(strategy, {"slow": 12, "bar": "15-MINUTE-LAST"})

    assert strategy.warmup(params) == timedelta(hours=3)


@pytest.mark.unit
def test_the_crossover_reads_the_bars_it_is_given() -> None:
    strategy = import_strategy(PATH)
    params = resolve_params(strategy, {"bar": "4-HOUR-LAST"})

    assert list(strategy.inputs(params)) == [BarSpecification.from_str("4-HOUR-LAST")]


def crossover(params: dict[str, Any]) -> MovingAverageCross:
    return MovingAverageCross(minute_bars(params))


@pytest.mark.integration
def test_the_crossover_does_not_trade_before_the_slow_average_is_warm() -> None:
    engine = run(crossover({"fast": 2, "slow": 5}), [10_000, 10_010, 10_020, 10_030])

    assert engine.cache.orders() == []


@pytest.mark.integration
def test_the_crossover_goes_long_when_the_fast_average_is_above_the_slow() -> None:
    engine = run(crossover(AVERAGES), RISING)

    orders = orders_of(engine, OrderType.MARKET)
    assert [(order.side, order.quantity) for order in orders] == [
        (OrderSide.BUY, QUANTITY)
    ]
    assert engine.portfolio.net_position(BTC) == QUANTITY.as_decimal()


@pytest.mark.integration
def test_the_crossover_reverses_to_short_when_the_fast_average_crosses_below() -> None:
    engine = run(crossover(AVERAGES), [*RISING[:4], 9_900, 9_800, 9_700])

    orders = orders_of(engine, OrderType.MARKET)
    assert [(order.side, order.quantity) for order in orders] == [
        (OrderSide.BUY, QUANTITY),
        (OrderSide.SELL, Quantity.from_str("0.200")),
    ]
    assert engine.portfolio.net_position(BTC) == -QUANTITY.as_decimal()


@pytest.mark.integration
def test_the_crossover_does_not_trade_while_the_averages_are_equal() -> None:
    engine = run(crossover(AVERAGES), [10_000] * 8)

    assert engine.cache.orders() == []
