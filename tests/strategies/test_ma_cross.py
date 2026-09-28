from datetime import timedelta

import pytest
from nautilus_trader.model import BarSpecification

from sbt2.strategy import import_strategy, resolve_params

PATH = "strategies.ma_cross:MovingAverageCross"


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
