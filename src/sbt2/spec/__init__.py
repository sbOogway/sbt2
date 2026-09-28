from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sbt2.spec.parse import read_spec
from sbt2.spec.resolve import InstrumentVenueError, resolve
from sbt2.spec.resolved import ResolvedRunSpec
from sbt2.spec.venues import UnknownVenueProfileError

__all__ = [
    "VENUE_PROFILES",
    "InstrumentVenueError",
    "ResolvedRunSpec",
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
