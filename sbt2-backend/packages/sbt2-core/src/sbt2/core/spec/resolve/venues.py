from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nautilus_trader.model import AssetClass, InstrumentClass

from sbt2.core.assets import AssetProfile, UnknownAssetClassError, asset_profile
from sbt2.core.spec.errors import SpecError
from sbt2.core.spec.resolve.models import built_model, model_tables
from sbt2.core.tomlfiles import read_toml, write_toml


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
    if not path.exists():
        raise MissingConfigError(f"no venue profiles file {path}")
    profiles = venue_profiles(path)
    if name not in profiles:
        raise _unknown(path, name, profiles)
    return _parsed(name, profiles[name])


def venue_profiles(path: Path) -> dict[str, dict[str, Any]]:
    """Every venue profile in ``path`` as stored, without the asset profile's
    venue defaults; none when the file is missing."""
    return read_toml(path)


def put_venue_profile(path: Path, name: str, table: Mapping[str, Any]) -> None:
    """Store ``table`` as the venue profile ``name``, replacing the one of that
    name; an invalid ``table`` raises and leaves the file as it was."""
    _parsed(name, table)
    profiles = venue_profiles(path)
    profiles[name] = dict(table)
    try:
        write_toml(path, profiles)
    except TypeError as error:
        raise InvalidVenueProfileError(
            f"the venue profile {name} holds a value TOML cannot: {error}"
        ) from error


def delete_venue_profile(path: Path, name: str) -> None:
    """Remove the venue profile ``name``, leaving the others."""
    profiles = venue_profiles(path)
    if profiles.pop(name, None) is None:
        raise _unknown(path, name, profiles)
    write_toml(path, profiles)


def _parsed(name: str, table: Mapping[str, Any]) -> VenueProfile:
    arguments = dict(table)
    if "source" not in arguments:
        raise InvalidVenueProfileError(f"the venue profile {name} names no source")
    source = arguments.pop("source")
    asset = _asset(
        name,
        arguments.pop("asset_class", None),
        arguments.pop("instrument_class", None),
    )
    _check_models(name, arguments)
    return VenueProfile(asset, source, {**asset.venue_defaults, **arguments})


def _asset(name: str, asset_class: Any, instrument_class: Any) -> AssetProfile:
    try:
        return asset_profile(
            AssetClass.from_str(asset_class), InstrumentClass.from_str(instrument_class)
        )
    except (TypeError, ValueError, UnknownAssetClassError) as error:
        raise InvalidVenueProfileError(
            f"the venue profile {name} names no known asset and instrument class: "
            f"{error}"
        ) from error


def _check_models(name: str, arguments: Mapping[str, Any]) -> None:
    for argument, table in model_tables(arguments):
        if "kind" not in table:
            raise InvalidVenueProfileError(
                f"the venue profile {name} names no {argument} kind; "
                "models are not named by import path, name a kind"
            )
        built_model(argument, table)


def _unknown(
    path: Path, name: str, profiles: Mapping[str, Any]
) -> UnknownVenueProfileError:
    return UnknownVenueProfileError(
        f"no venue profile {name} in {path}; known: {', '.join(sorted(profiles))}"
    )
