"""Requests that start runs: spec tables as the messages that carry them."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from typing import Any

from google.protobuf.struct_pb2 import Struct

from sbt2.protocol.v1.runs_pb2 import SpecFile

_PLAIN = (
    "strategy",
    "instruments",
    "venue",
    "capital",
    "seed",
    "equity_interval",
    "liquidation",
    "bars",
    "study",
)


def struct(values: Mapping[str, Any]) -> Struct:
    message = Struct()
    message.update(_jsonable(values))
    return message


def spec_message(table: Mapping[str, Any]) -> SpecFile:
    """The ``SpecFile`` that carries a spec file's ``table``."""
    message = SpecFile(
        **{key: table[key] for key in _PLAIN if key in table},
        part=_parts(table.get("part", [])),
        split=struct(table.get("split", {})),
        params=struct(table.get("params", {})),
        risk=struct(table.get("risk", {})),
    )
    if "period" in table:
        start, end = table["period"]
        message.period.start_at.FromDatetime(_utc(start))
        message.period.end_at.FromDatetime(_utc(end))
    return message


def _parts(part: str | list[str]) -> list[str]:
    return [part] if isinstance(part, str) else part


def _utc(moment: date | datetime) -> datetime:
    if isinstance(moment, datetime):
        return moment.replace(tzinfo=moment.tzinfo or UTC)
    return datetime.combine(moment, time(), tzinfo=UTC)


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _jsonable(each) for key, each in value.items()}
    if isinstance(value, list):
        return [_jsonable(each) for each in value]
    return value
