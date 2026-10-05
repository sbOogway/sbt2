from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sbt2.core.spec.errors import SpecError
from sbt2.core.spec.file import Expanded, RunSpec, runs, table_runs
from sbt2.core.spec.resolve import ResolvedRunSpec, resolve


class DuplicateRunError(SpecError):
    """Two runs of a spec file that resolve to the same backtest."""


def load(
    path: Path,
    venue_profiles: Path,
    overrides: Mapping[str, Any] | None = None,
) -> list[ResolvedRunSpec]:
    """Read a spec file, apply top-level ``overrides`` and resolve every run it
    expands into against the venue profiles file ``venue_profiles``; one run
    that fails to resolve fails them all."""
    return _resolved_all(runs(path, overrides or {}), venue_profiles)


def load_table(
    table: Mapping[str, Any],
    venue_profiles: Path,
    overrides: Mapping[str, Any] | None = None,
) -> list[ResolvedRunSpec]:
    """``load`` for a spec given as a table, such as a spec file parses into."""
    return _resolved_all(table_runs(table, overrides or {}), venue_profiles)


def _resolved_all(
    expanded: list[Expanded], venue_profiles: Path
) -> list[ResolvedRunSpec]:
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
