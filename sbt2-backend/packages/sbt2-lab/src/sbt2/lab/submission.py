import importlib.util
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

from google.protobuf.struct_pb2 import Struct

from sbt2.lab.errors import StrategyModuleError
from sbt2.protocol.v1.runs_pb2 import SpecFile, SpecPeriod, StrategyModule, SubmitRun

_PLAIN = ("instruments", "venue", "capital", "seed", "equity_interval")
_OPTIONAL = ("liquidation", "bars", "study")
_TABLES = ("split", "params", "risk")
_KEYS = {*_PLAIN, *_OPTIONAL, *_TABLES, "period", "part"}

type Moment = date | datetime | str


def submit_run(spec: Mapping[str, Any], strategy: str) -> SubmitRun:
    """The request that runs ``spec`` with the class ``strategy``, given as
    ``"module:Class"``, whose module is sent as source."""
    _check_keys(spec)
    module_path, class_name = _parts(strategy)
    module = _module(module_path)
    wire = _spec_file(spec)
    wire.strategy = f"{module.name}:{class_name}"
    return SubmitRun(spec=wire, strategy=module)


def _check_keys(spec: Mapping[str, Any]) -> None:
    if "strategy" in spec:
        raise ValueError("give the strategy as the argument of run, not in the spec")
    unknown = sorted(set(spec) - _KEYS)
    if unknown:
        raise ValueError(
            f"unknown spec keys {', '.join(unknown)}; valid: {', '.join(sorted(_KEYS))}"
        )


def _parts(strategy: str) -> tuple[str, str]:
    module_path, _, class_name = strategy.partition(":")
    if not module_path or not class_name:
        raise ValueError(f"give the strategy as 'module:Class', not {strategy!r}")
    return module_path, class_name


def _module(path: str) -> StrategyModule:
    """The module at ``path`` as source; ``find_spec`` runs no code of the
    module, only of the packages that hold it."""
    try:
        found = importlib.util.find_spec(path)
    except ImportError as error:
        raise StrategyModuleError(f"cannot find the module {path}: {error}") from error
    if found is None or found.origin is None or not found.has_location:
        raise StrategyModuleError(f"cannot find the source of the module {path}")
    source = Path(found.origin).read_text()
    return StrategyModule(name=path.rpartition(".")[2], source=source)


def _spec_file(spec: Mapping[str, Any]) -> SpecFile:
    wire = SpecFile()
    for key in _PLAIN + _OPTIONAL:
        if key in spec:
            _set(wire, key, spec[key])
    if "period" in spec:
        wire.period.CopyFrom(_period(spec["period"]))
    if "part" in spec:
        part = spec["part"]
        wire.part.extend([part] if isinstance(part, str) else part)
    for key in _TABLES:
        if key in spec:
            getattr(wire, key).CopyFrom(_struct(spec[key]))
    return wire


def _set(wire: SpecFile, key: str, value: Any) -> None:
    if key == "instruments":
        wire.instruments.extend(value)
    else:
        setattr(wire, key, value)


def _period(period: tuple[Moment, Moment]) -> SpecPeriod:
    start, end = period
    wire = SpecPeriod()
    wire.start_at.FromDatetime(_utc(start))
    wire.end_at.FromDatetime(_utc(end))
    return wire


def _utc(moment: Moment) -> datetime:
    """A date or datetime as an aware UTC datetime; naive values are UTC, as in
    a spec file."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if not isinstance(moment, datetime):
        moment = datetime.combine(moment, time())
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _struct(table: Mapping[str, Any]) -> Struct:
    wire = Struct()
    wire.update({key: _plain(value) for key, value in table.items()})
    return wire


def _plain(value: Any) -> Any:
    """``value`` in the JSON types a ``Struct`` holds."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {key: _plain(each) for key, each in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(each) for each in value]
    return value
