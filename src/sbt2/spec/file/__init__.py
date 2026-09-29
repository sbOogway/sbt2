from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sbt2.spec.file.expand import EmptyListError, Expanded, expand
from sbt2.spec.file.read import MissingSplitError, UnknownSpecKeyError, read_spec
from sbt2.spec.file.run_spec import RunSpec


def runs(path: Path, overrides: Mapping[str, Any]) -> list[Expanded]:
    """Each run a spec file describes once ``overrides`` replace its top-level
    keys, as a table ready to become a ``RunSpec``."""
    return expand(read_spec(path, overrides))


__all__ = [
    "EmptyListError",
    "Expanded",
    "MissingSplitError",
    "RunSpec",
    "UnknownSpecKeyError",
    "runs",
]
