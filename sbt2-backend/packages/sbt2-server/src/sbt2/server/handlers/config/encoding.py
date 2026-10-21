from collections.abc import Mapping
from datetime import date

from google.protobuf import json_format
from google.protobuf.struct_pb2 import Value

from sbt2 import data
from sbt2.core import spec
from sbt2.protocol.v1.config_pb2 import (
    KnownGap,
    ModelArgument,
    ModelArgumentKinds,
    ModelKind,
    ModelKinds,
    ModelParameter,
    ParameterType,
)

_PARAMETER_TYPES = {
    str: ParameterType.PARAMETER_TYPE_STRING,
    int: ParameterType.PARAMETER_TYPE_INTEGER,
    float: ParameterType.PARAMETER_TYPE_NUMBER,
    bool: ParameterType.PARAMETER_TYPE_BOOLEAN,
}


class InvalidArgumentError(ValueError):
    """A request the server cannot translate for core; its message says why."""


def listed_gap(gap: KnownGap) -> data.ListedGap:
    """The gap as core lists it."""
    try:
        day = date.fromisoformat(gap.day)
    except ValueError as error:
        raise InvalidArgumentError(f"the day of a known gap: {error}") from error
    return data.ListedGap(gap.source, gap.symbol, gap.data_type, day)


def gap_message(gap: data.ListedGap) -> KnownGap:
    return KnownGap(
        source=gap.source,
        symbol=gap.symbol,
        data_type=gap.data,
        day=gap.day.isoformat(),
    )


def model_kinds(
    kinds: Mapping[str, Mapping[str, tuple[spec.ModelParameter, ...]]],
) -> ModelKinds:
    """Core's model ``kinds``, by model argument."""
    return ModelKinds(
        arguments=[
            ModelArgumentKinds(
                argument=ModelArgument.Value(f"MODEL_ARGUMENT_{argument.upper()}"),
                kinds=[
                    ModelKind(
                        name=kind, parameters=[_parameter(each) for each in params]
                    )
                    for kind, params in each_kind.items()
                ],
            )
            for argument, each_kind in kinds.items()
        ]
    )


def _parameter(parameter: spec.ModelParameter) -> ModelParameter:
    message = ModelParameter(
        name=parameter.name,
        type=_PARAMETER_TYPES[parameter.type],
        required=parameter.required,
    )
    if parameter.default is not None:
        message.default.CopyFrom(json_format.ParseDict(parameter.default, Value()))
    return message
