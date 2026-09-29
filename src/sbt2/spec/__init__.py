from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sbt2.spec.parse import UnknownSpecKeyError, read_spec
from sbt2.spec.resolve import (
    CandleBarError,
    InstrumentVenueError,
    MissingPartError,
    MissingSplitError,
    ResolvedRunSpec,
    UnknownBarSourceError,
    UnknownPartError,
    resolve,
)
from sbt2.spec.split import (
    Split,
    SplitDateError,
    SplitFormError,
    SplitFractionError,
    Splitter,
    UnknownSplitError,
)
from sbt2.spec.venues import InvalidVenueProfileError, UnknownVenueProfileError

__all__ = [
    "VENUE_PROFILES",
    "CandleBarError",
    "InstrumentVenueError",
    "InvalidVenueProfileError",
    "MissingPartError",
    "MissingSplitError",
    "ResolvedRunSpec",
    "Split",
    "SplitDateError",
    "SplitFormError",
    "SplitFractionError",
    "Splitter",
    "UnknownBarSourceError",
    "UnknownPartError",
    "UnknownSpecKeyError",
    "UnknownSplitError",
    "UnknownVenueProfileError",
    "load",
]

VENUE_PROFILES = Path("config/venues.toml")


def load(
    path: Path,
    overrides: Mapping[str, Any] | None = None,
    venue_profiles: Path = VENUE_PROFILES,
) -> ResolvedRunSpec:
    """Read a spec file, apply top-level ``overrides`` and resolve it."""
    return resolve(read_spec(path, overrides or {}), venue_profiles)
