from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sbt2.spec.expand import Expanded, expand
from sbt2.spec.parse import RunSpec, UnknownSpecKeyError, read_spec
from sbt2.spec.resolve import (
    CandleBarError,
    InstrumentVenueError,
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
) -> list[ResolvedRunSpec]:
    """Read a spec file, apply top-level ``overrides`` and resolve its runs."""
    table = read_spec(path, overrides or {})
    return [_resolved(each, venue_profiles) for each in expand(table)]


def _resolved(run: Expanded, venue_profiles: Path) -> ResolvedRunSpec:
    try:
        return resolve(RunSpec(**run.table), venue_profiles)
    except Exception as error:
        error.add_note(f"in {run.name}")
        raise
