from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, override

import pytest
from google.protobuf.struct_pb2 import Value
from nautilus_trader.model import BarSpecification

from sbt2.core.strategy import Strategy
from sbt2.protocol.v1.config_pb2 import ParameterType
from sbt2.protocol.v1.runs_pb2 import StrategyParameter
from sbt2.server.strategies.encoding import describe


@dataclass(frozen=True)
class Knobs:
    """The knobs."""

    window: int
    step: Decimal = Decimal("0.100")
    scale: float = 0.5
    mode: Literal["ema", "sma"] = "ema"
    live: bool = False


class Knobbed(Strategy[Knobs]):
    """Turns the knobs."""

    Params = Knobs

    @classmethod
    @override
    def inputs(cls, params: Knobs) -> Sequence[BarSpecification]:
        return ()


def number(value: float) -> Value:
    return Value(number_value=value)


def text(value: str) -> Value:
    return Value(string_value=value)


@pytest.mark.unit
def test_parameter_defaults_and_choices_encode_with_decimals_as_strings() -> None:
    schema = describe(Knobbed)

    assert (schema.strategy, schema.description) == (
        f"{__name__}:Knobbed",
        "Turns the knobs.",
    )
    assert schema.params_description == "The knobs."
    assert list(schema.parameters) == [
        StrategyParameter(
            name="window", type=ParameterType.PARAMETER_TYPE_INTEGER, required=True
        ),
        StrategyParameter(
            name="step",
            type=ParameterType.PARAMETER_TYPE_DECIMAL,
            default=text("0.100"),
        ),
        StrategyParameter(
            name="scale", type=ParameterType.PARAMETER_TYPE_NUMBER, default=number(0.5)
        ),
        StrategyParameter(
            name="mode",
            type=ParameterType.PARAMETER_TYPE_STRING,
            default=text("ema"),
            choices=[text("ema"), text("sma")],
        ),
        StrategyParameter(
            name="live",
            type=ParameterType.PARAMETER_TYPE_BOOLEAN,
            default=Value(bool_value=False),
        ),
    ]
    assert not schema.parameters[0].HasField("default")
