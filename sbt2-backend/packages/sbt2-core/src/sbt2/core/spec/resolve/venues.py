import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nautilus_trader.model import AssetClass, InstrumentClass

from sbt2.core.assets import AssetProfile, asset_profile
from sbt2.core.spec.errors import SpecError
from sbt2.core.spec.resolve.models import built_model, model_tables


class UnknownVenueProfileError(SpecError, LookupError):
    pass


class InvalidVenueProfileError(SpecError):
    pass


class MissingConfigError(SpecError):
    """A configuration file a run reads that does not exist."""


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
    as ``{kind, config}`` tables until the run config builds them.
    """
    arguments = _profile_table(path, name)
    if "source" not in arguments:
        raise InvalidVenueProfileError(f"the venue profile {name} names no source")
    source = arguments.pop("source")
    asset = asset_profile(
        AssetClass.from_str(arguments.pop("asset_class")),
        InstrumentClass.from_str(arguments.pop("instrument_class")),
    )
    _check_models(name, arguments)
    return VenueProfile(asset, source, {**asset.venue_defaults, **arguments})


def _check_models(name: str, arguments: Mapping[str, Any]) -> None:
    for argument, table in model_tables(arguments):
        if "kind" not in table:
            raise InvalidVenueProfileError(
                f"the venue profile {name} names no {argument} kind; "
                "models are not named by import path, name a kind"
            )
        built_model(argument, table)


def venue_profiles(path: Path) -> dict[str, dict[str, Any]]:
    """Every venue profile in ``path`` as stored, without the asset profile's
    venue defaults; none when the file is missing."""
    if not path.exists():
        return {}
    with path.open("rb") as file:
        return tomllib.load(file)


def _profile_table(path: Path, name: str) -> dict[str, Any]:
    if not path.exists():
        raise MissingConfigError(f"no venue profiles file {path}")
    profiles = venue_profiles(path)
    try:
        return dict(profiles[name])
    except KeyError:
        raise UnknownVenueProfileError(
            f"no venue profile {name} in {path}; known: {', '.join(sorted(profiles))}"
        ) from None
