import tomllib
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any

from sbt2.core.spec.errors import SpecError
from sbt2.core.spec.file.run_spec import RunSpec


class UnknownSpecKeyError(SpecError):
    pass


class MissingSplitError(SpecError):
    pass


def read_spec(path: Path, overrides: Mapping[str, Any]) -> dict[str, Any]:
    """A spec file's table with ``overrides`` applied, before it is expanded."""
    with path.open("rb") as file:
        table = tomllib.load(file)
    return checked_table(table, overrides, str(path))


def checked_table(
    table: Mapping[str, Any], overrides: Mapping[str, Any], origin: str
) -> dict[str, Any]:
    """A spec's ``table`` with ``overrides`` applied, from ``origin``, which the
    errors name."""
    values = {**table, **overrides}
    _reject_unknown(origin, values)
    if "split" not in values:
        raise MissingSplitError(f"{origin} needs a split of its period")
    return values


def _reject_unknown(origin: str, values: Mapping[str, Any]) -> None:
    valid = {each.name for each in fields(RunSpec)}
    unknown = sorted(set(values) - valid)
    if unknown:
        raise UnknownSpecKeyError(
            f"unknown keys {', '.join(unknown)} in {origin}; "
            f"valid: {', '.join(sorted(valid))}"
        )
