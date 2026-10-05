from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sbt2.core.spec.file.expand import EmptyListError, Expanded, expand
from sbt2.core.spec.file.read import (
    MissingSplitError,
    UnknownSpecKeyError,
    checked_table,
    read_spec,
)
from sbt2.core.spec.file.run_spec import InvalidStudyNameError, RunSpec


def runs(path: Path, overrides: Mapping[str, Any]) -> list[Expanded]:
    """Each run a spec file describes once ``overrides`` replace its top-level
    keys, as a table ready to become a ``RunSpec``."""
    return expand(read_spec(path, overrides))


def table_runs(
    table: Mapping[str, Any], overrides: Mapping[str, Any]
) -> list[Expanded]:
    """``runs`` for a spec given as a table instead of a file."""
    return expand(checked_table(table, overrides, "the spec"))


__all__ = [
    "EmptyListError",
    "Expanded",
    "InvalidStudyNameError",
    "MissingSplitError",
    "RunSpec",
    "UnknownSpecKeyError",
    "runs",
    "table_runs",
]
