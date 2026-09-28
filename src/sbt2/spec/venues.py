import importlib
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nautilus_trader.model import AssetClass, InstrumentClass

from sbt2.assets import AssetProfile, asset_profile

_MODEL_ARGUMENTS = ("fee_model", "fill_model", "latency_model", "margin_model")


class UnknownVenueProfileError(LookupError):
    pass


def venue_profile(path: Path, name: str) -> tuple[AssetProfile, dict[str, Any]]:
    """The asset profile a venue profile names, and its ``BacktestVenueConfig`` arguments.

    The arguments start from the asset profile's venue defaults. Model arguments stay
    as ``{path, config}`` tables until ``venue_objects`` imports them.
    """
    arguments = _profile_table(path, name)
    asset = asset_profile(
        AssetClass.from_str(arguments.pop("asset_class")),
        InstrumentClass.from_str(arguments.pop("instrument_class")),
    )
    return asset, {**asset.venue_defaults, **arguments}


def venue_objects(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Venue arguments with each ``{path, config}`` model table imported and built."""
    built = dict(arguments)
    for name in _MODEL_ARGUMENTS:
        if name in built:
            built[name] = _built(built[name])
    if "modules" in built:
        built["modules"] = [_built(each) for each in built["modules"]]
    return built


def _profile_table(path: Path, name: str) -> dict[str, Any]:
    with path.open("rb") as file:
        profiles = tomllib.load(file)
    try:
        return dict(profiles[name])
    except KeyError:
        raise UnknownVenueProfileError(
            f"no venue profile {name} in {path}; known: {', '.join(sorted(profiles))}"
        ) from None


def _built(model: Mapping[str, Any]) -> Any:
    module_name, _, class_name = model["path"].partition(":")
    kind = getattr(importlib.import_module(module_name), class_name)
    return kind(**model.get("config", {}))
