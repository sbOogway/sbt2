from collections.abc import Mapping
from datetime import date
from typing import Any

from google.protobuf import json_format

from sbt2.protocol.v1.config_pb2 import (
    AssetClass,
    InstrumentClass,
    VenueModel,
    VenueProfile,
)

MODELS = ("fee_model", "fill_model", "latency_model", "margin_model")
_TYPED = frozenset({"name", "source", "asset_class", "instrument_class", "modules"})
_RESERVED = _TYPED | frozenset(MODELS)


class InvalidArgumentError(ValueError):
    """A request the server cannot translate for core; its message says why."""


def profile_table(profile: VenueProfile) -> dict[str, Any]:
    """The venue profile's table, as core stores it."""
    arguments = _integral(json_format.MessageToDict(profile.arguments))
    clashing = sorted(set(arguments) & _RESERVED)
    if clashing:
        raise InvalidArgumentError(
            f"set {', '.join(clashing)} in its own field, not in arguments"
        )
    return {**_typed_table(profile), **arguments}


def profile_message(name: str, table: Mapping[str, Any]) -> VenueProfile:
    """The venue profile ``name`` that core stores as ``table``."""
    rest = dict(table)
    profile = VenueProfile(
        name=name,
        venue=str(rest.pop("name", "")),
        source=str(rest.pop("source", "")),
        asset_class=_asset_class(rest.pop("asset_class", "")),
        instrument_class=_instrument_class(rest.pop("instrument_class", "")),
    )
    for argument in MODELS:
        if argument in rest:
            getattr(profile, argument).CopyFrom(_model_message(rest.pop(argument)))
    profile.modules.extend(_model_message(each) for each in rest.pop("modules", []))
    if rest:
        profile.arguments.update(_jsonable(rest))
    return profile


def _typed_table(profile: VenueProfile) -> dict[str, Any]:
    table: dict[str, Any] = {}
    if profile.venue:
        table["name"] = profile.venue
    if profile.source:
        table["source"] = profile.source
    if profile.asset_class:
        table["asset_class"] = _enum_name(AssetClass.Name(profile.asset_class))
    if profile.instrument_class:
        name = InstrumentClass.Name(profile.instrument_class)
        table["instrument_class"] = _enum_name(name)
    for argument in MODELS:
        if profile.HasField(argument):
            table[argument] = _model_table(getattr(profile, argument))
    if profile.modules:
        table["modules"] = [_model_table(each) for each in profile.modules]
    return table


def _model_table(model: VenueModel) -> dict[str, Any]:
    table: dict[str, Any] = {"kind": model.kind}
    if model.HasField("config"):
        table["config"] = _integral(json_format.MessageToDict(model.config))
    return table


def _model_message(table: Mapping[str, Any]) -> VenueModel:
    model = VenueModel(kind=str(table.get("kind", "")))
    if "config" in table:
        model.config.update(_jsonable(table["config"]))
    return model


def _enum_name(name: str) -> str:
    """The nautilus name of a protocol enum value, its prefix dropped."""
    return name.split("_CLASS_", 1)[1]


def _asset_class(value: Any) -> AssetClass.ValueType:
    try:
        return AssetClass.Value(f"ASSET_CLASS_{str(value).upper()}")
    except ValueError:
        return AssetClass.ASSET_CLASS_UNSPECIFIED


def _instrument_class(value: Any) -> InstrumentClass.ValueType:
    try:
        return InstrumentClass.Value(f"INSTRUMENT_CLASS_{str(value).upper()}")
    except ValueError:
        return InstrumentClass.INSTRUMENT_CLASS_UNSPECIFIED


def _integral(value: Any) -> Any:
    """``value`` with each integral float made an int: a Struct holds no ints."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _integral(each) for key, each in value.items()}
    if isinstance(value, list):
        return [_integral(each) for each in value]
    return value


def _jsonable(value: Any) -> Any:
    """``value`` as a Struct can hold it, dates as ISO strings."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {key: _jsonable(each) for key, each in value.items()}
    if isinstance(value, list):
        return [_jsonable(each) for each in value]
    return value
