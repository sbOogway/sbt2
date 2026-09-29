from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sbt2.config import VENUE_PROFILES
from sbt2.spec.file import Expanded, RunSpec, runs
from sbt2.spec.resolve import ResolvedRunSpec, resolve


class DuplicateRunError(ValueError):
    """Two runs of a spec file that resolve to the same backtest."""


def load(
    path: Path,
    overrides: Mapping[str, Any] | None = None,
    venue_profiles: Path = VENUE_PROFILES,
) -> list[ResolvedRunSpec]:
    """Read a spec file, apply top-level ``overrides`` and resolve every run it
    expands into; one run that fails to resolve fails them all."""
    expanded = runs(path, overrides or {})
    resolved = [_resolved(each, venue_profiles) for each in expanded]
    _check_unique(expanded, resolved)
    return resolved


def _resolved(run: Expanded, venue_profiles: Path) -> ResolvedRunSpec:
    try:
        return resolve(RunSpec(**run.table), venue_profiles)
    except Exception as error:
        error.add_note(f"in {run.name}")
        raise


def _check_unique(runs: list[Expanded], resolved: list[ResolvedRunSpec]) -> None:
    seen: dict[str, Expanded] = {}
    for run, spec in zip(runs, resolved, strict=True):
        if spec.hash in seen:
            raise DuplicateRunError(
                f"{seen[spec.hash].name} and {run.name} are the same run"
            )
        seen[spec.hash] = run
