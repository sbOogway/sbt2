import importlib
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nautilus_trader.model import AssetClass, InstrumentClass

from sbt2.assets import AssetProfile, asset_profile
from sbt2.spec.errors import SpecError

_MODEL_ARGUMENTS = ("fee_model", "fill_model", "latency_model", "margin_model")


class UnknownVenueProfileError(SpecError, LookupError):
    pass


class InvalidVenueProfileError(SpecError):
    pass


@dataclass(frozen=True)
class VenueProfile:
    """``arguments`` are the ``BacktestVenueConfig`` arguments; ``source`` names
    the data source the venue's data comes from."""

    asset: AssetProfile
    source: str
    arguments: dict[str, Any]


def venue_profile(path: Path, name: str) -> VenueProfile:
    """The venue profile called ``name``.

    The arguments start from the asset profile's venue defaults. Model arguments stay
    as ``{path, config}`` tables until ``venue_objects`` imports them.
    """
    arguments = _profile_table(path, name)
    if "source" not in arguments:
        raise InvalidVenueProfileError(f"the venue profile {name} names no source")
    source = arguments.pop("source")
    asset = asset_profile(
        AssetClass.from_str(arguments.pop("asset_class")),
        InstrumentClass.from_str(arguments.pop("instrument_class")),
    )
    return VenueProfile(asset, source, {**asset.venue_defaults, **arguments})


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
