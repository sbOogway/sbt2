import inspect
from decimal import Decimal
from typing import Any

from google.protobuf.struct_pb2 import Value

from sbt2.core.strategy import ParamSpec, Strategy, params_schema
from sbt2.protocol.v1.config_pb2 import ParameterType
from sbt2.protocol.v1.runs_pb2 import StrategyParameter, StrategySchema

_TYPES: dict[type, ParameterType.ValueType] = {
    int: ParameterType.PARAMETER_TYPE_INTEGER,
    float: ParameterType.PARAMETER_TYPE_NUMBER,
    Decimal: ParameterType.PARAMETER_TYPE_DECIMAL,
    str: ParameterType.PARAMETER_TYPE_STRING,
    bool: ParameterType.PARAMETER_TYPE_BOOLEAN,
}


class InvalidArgumentError(ValueError):
    """A request the server answers INVALID_ARGUMENT; its message says why."""


def describe(strategy: type[Strategy[Any]]) -> StrategySchema:
    """The schema of ``strategy.Params``, as the protocol carries it."""
    return StrategySchema(
        strategy=f"{strategy.__module__}:{strategy.__qualname__}",
        description=_docstring(strategy),
        params_description=_docstring(strategy.Params),
        parameters=[_parameter(each) for each in params_schema(strategy)],
    )


def _docstring(kind: type) -> str:
    """What the class itself says: not a docstring it inherits, nor the
    signature that ``dataclass`` writes when there is none."""
    doc = vars(kind).get("__doc__")
    if not isinstance(doc, str) or doc.startswith(f"{kind.__name__}("):
        return ""
    return inspect.cleandoc(doc)


def _parameter(spec: ParamSpec) -> StrategyParameter:
    parameter = StrategyParameter(
        name=spec.name,
        type=_TYPES[spec.kind],
        required=spec.required,
        choices=[_value(each) for each in spec.choices],
    )
    if not spec.required:
        parameter.default.CopyFrom(_value(spec.default))
    return parameter


def _value(value: Any) -> Value:
    if isinstance(value, bool):
        return Value(bool_value=value)
    if isinstance(value, int | float):
        return Value(number_value=value)
    return Value(string_value=str(value))
