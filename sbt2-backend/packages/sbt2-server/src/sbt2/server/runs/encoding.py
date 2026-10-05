from datetime import UTC
from typing import Any

from google.protobuf import json_format
from google.protobuf.struct_pb2 import Struct

from sbt2.protocol.v1.runs_pb2 import SpecFile, SubmitRun
from sbt2.server.modules import module_name_problem
from sbt2.server.runs.jobs import Module, Submission

_REQUIRED = ("strategy", "instruments", "period", "venue", "capital")
_OPTIONAL = ("seed", "equity_interval", "liquidation", "bars", "study")
_TABLES = ("split", "params", "risk")


class InvalidArgumentError(ValueError):
    """A request the server cannot translate for core; its message says why."""


def spec_table(spec: SpecFile) -> dict[str, Any]:
    """The spec file's table the message carries, as core reads it; what the
    message leaves unset is not in the table."""
    missing = [key for key in _REQUIRED if not _is_set(spec, key)]
    if missing:
        raise InvalidArgumentError(f"the spec needs {', '.join(missing)}")
    table: dict[str, Any] = {
        "strategy": spec.strategy,
        "instruments": list(spec.instruments),
        "period": _period(spec),
        "venue": spec.venue,
        "capital": spec.capital,
    }
    if spec.part:
        table["part"] = list(spec.part)
    for key in _OPTIONAL:
        if spec.HasField(key):
            table[key] = getattr(spec, key)
    for key in _TABLES:
        if getattr(spec, key).fields:
            table[key] = _table(getattr(spec, key))
    return table


def _is_set(spec: SpecFile, key: str) -> bool:
    if key == "period":
        return spec.period.HasField("start_at") and spec.period.HasField("end_at")
    return bool(getattr(spec, key))


def _period(spec: SpecFile) -> list[Any]:
    return [
        spec.period.start_at.ToDatetime(tzinfo=UTC),
        spec.period.end_at.ToDatetime(tzinfo=UTC),
    ]


def _table(message: Struct) -> dict[str, Any]:
    return _integral(json_format.MessageToDict(message))


def _integral(value: Any) -> Any:
    """``value`` with each integral float made an int: a Struct holds no ints."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _integral(each) for key, each in value.items()}
    if isinstance(value, list):
        return [_integral(each) for each in value]
    return value


def submission(request: SubmitRun) -> Submission:
    """What a ``SubmitRun`` asks for, in the types the jobs take."""
    table = spec_table(request.spec)
    module = request.strategy
    _check_module(module.name, module.source, table["strategy"])
    return Submission(table, Module(module.name, module.source))


def _check_module(name: str, source: str, strategy: str) -> None:
    if problem := module_name_problem(name):
        raise InvalidArgumentError(problem)
    if strategy.partition(":")[0] != name or ":" not in strategy:
        raise InvalidArgumentError(
            f"the strategy {strategy!r} must be a class of the module {name}, "
            f"as {name}:Class"
        )
    if not source.strip():
        raise InvalidArgumentError(f"the source of the module {name} is empty")
