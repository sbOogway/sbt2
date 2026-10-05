from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any, Literal

import pytest
from toy_strategies import BuyEveryBar, CountWarmupBars

from sbt2.core.strategy import (
    InvalidParameterError,
    Strategy,
    UnsupportedParameterTypeError,
    params_schema,
    resolve_params,
)


@dataclass(frozen=True)
class ModeParams:
    mode: Literal["fast", "slow"] = "fast"


class ModeStrategy(BuyEveryBar):
    Params = ModeParams


@dataclass(frozen=True)
class AllKinds:
    count: int = 3
    ratio: float = 0.5
    step: Decimal = Decimal("0.100")
    label: str = "x"
    enabled: bool = True


@dataclass(frozen=True)
class Required:
    window: int
    mode: Literal["fast", "slow"] = "fast"


@dataclass(frozen=True)
class Spans:
    span: timedelta


@dataclass(frozen=True)
class Lists:
    sizes: list[int]


@dataclass(frozen=True)
class Mixed:
    pick: Literal[1, "a"]


def strategy_with(params: type) -> type[Strategy[Any]]:
    return type("Described", (BuyEveryBar,), {"Params": params})


@pytest.mark.unit
def test_a_value_outside_a_literal_is_rejected() -> None:
    assert resolve_params(ModeStrategy, {"mode": "slow"}) == ModeParams("slow")
    with pytest.raises(InvalidParameterError, match="mode must be one of"):
        resolve_params(ModeStrategy, {"mode": "medium"})


@pytest.mark.unit
def test_params_schema_lists_each_field_with_its_type_and_default() -> None:
    schema = params_schema(strategy_with(AllKinds))

    assert [(each.name, each.kind, each.default) for each in schema] == [
        ("count", int, 3),
        ("ratio", float, 0.5),
        ("step", Decimal, Decimal("0.100")),
        ("label", str, "x"),
        ("enabled", bool, True),
    ]


@pytest.mark.unit
def test_a_field_without_a_default_is_required() -> None:
    window, mode = params_schema(strategy_with(Required))

    assert (window.required, window.default) == (True, None)
    assert (mode.required, mode.default) == (False, "fast")


@pytest.mark.unit
def test_a_literal_field_lists_its_choices() -> None:
    _, mode = params_schema(strategy_with(Required))

    assert (mode.kind, mode.choices) == (str, ("fast", "slow"))


@pytest.mark.unit
def test_a_strategy_without_params_has_an_empty_schema() -> None:
    assert params_schema(CountWarmupBars) == ()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("params", "field", "kind"),
    [
        (Spans, "span", "timedelta"),
        (Lists, "sizes", "list[int]"),
        (Mixed, "pick", "Literal[1, 'a']"),
    ],
)
def test_a_field_of_an_unsupported_type_raises_naming_it(
    params: type, field: str, kind: str
) -> None:
    with pytest.raises(UnsupportedParameterTypeError) as raised:
        params_schema(strategy_with(params))

    assert field in str(raised.value)
    assert kind in str(raised.value)
