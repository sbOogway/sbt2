from datetime import timedelta
from decimal import Decimal

import pytest
from nautilus_trader.model import BarType, InstrumentId
from toy_strategies import BuyEveryBar, CountWarmupBars, StepParams

from sbt2.strategy import (
    Bars,
    InvalidParameterError,
    NoParams,
    UnknownParameterError,
    import_strategy,
    resolve_params,
)

BTC = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")


def test_strategy_is_imported_by_path() -> None:
    assert import_strategy("toy_strategies:BuyEveryBar") is BuyEveryBar


def test_importing_something_else_fails() -> None:
    with pytest.raises(TypeError, match="not an sbt2 Strategy subclass"):
        import_strategy("toy_strategies:NotAStrategy")


def test_params_are_filled_in_from_the_defaults() -> None:
    params = resolve_params(BuyEveryBar, {"lookback": 5})

    assert params == StepParams(step=Decimal("0.100"), lookback=5)


def test_unknown_params_fail_listing_the_valid_ones() -> None:
    with pytest.raises(
        UnknownParameterError, match="loopback .* valid: lookback, step"
    ):
        resolve_params(BuyEveryBar, {"loopback": 5})


def test_strategy_without_params_takes_none() -> None:
    assert resolve_params(CountWarmupBars, {}) == NoParams()
    with pytest.raises(UnknownParameterError, match="valid: none"):
        resolve_params(CountWarmupBars, {"size": 1})


def test_warmup_and_inputs_are_read_without_running() -> None:
    params = StepParams(lookback=5)

    assert BuyEveryBar.warmup(params) == timedelta(minutes=5)
    assert BuyEveryBar.inputs(params) == (Bars("1-MINUTE-LAST"),)


def test_warmup_defaults_to_none() -> None:
    assert CountWarmupBars.warmup(NoParams()) == timedelta(0)


def test_bars_are_aggregated_internally() -> None:
    bar_type = Bars("1-MINUTE-LAST").bar_type(BTC)

    assert bar_type == BarType.from_str("BTCUSDT-PERP.BYBIT-1-MINUTE-LAST-INTERNAL")


@pytest.mark.parametrize("step", ["0.25", 0.25])
def test_decimal_params_are_parsed_from_plain_values(step: str | float) -> None:
    assert resolve_params(BuyEveryBar, {"step": step}).step == Decimal("0.25")


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"lookback": "5"}, "lookback must be int, got '5'"),
        ({"lookback": True}, "lookback must be int, got True"),
        ({"step": "a lot"}, "step must be a decimal, got 'a lot'"),
    ],
)
def test_params_of_the_wrong_type_fail(values: dict[str, object], message: str) -> None:
    with pytest.raises(InvalidParameterError, match=message):
        resolve_params(BuyEveryBar, values)
