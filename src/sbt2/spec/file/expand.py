from collections.abc import Mapping
from dataclasses import dataclass
from itertools import product
from typing import Any

from sbt2.spec.errors import SpecError

_UNNAMED_PARTS = ("train", "validation")


class EmptyListError(SpecError):
    """A list in a spec file that would expand into no runs."""


@dataclass(frozen=True)
class Expanded:
    """One run's table, and a name for it that shows which values it took."""

    table: dict[str, Any]
    name: str


def expand(table: Mapping[str, Any]) -> list[Expanded]:
    """One table per run a spec file's table describes.

    Without ``part``, a spec runs its train and validation parts; test must be
    asked for. Lists in ``params`` expand into their Cartesian product, in the
    order the file gives them.
    """
    params = table.get("params", {})
    return [
        Expanded({**table, "part": part, "params": chosen}, _name(part, params, chosen))
        for part in _parts(table.get("part"))
        for chosen in _combinations(params)
    ]


def _parts(part: str | list[str] | None) -> list[str]:
    if part is None:
        return list(_UNNAMED_PARTS)
    if isinstance(part, str):
        return [part]
    return _nonempty("part", part)


def _combinations(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    choices = [_values(key, value) for key, value in params.items()]
    return [dict(zip(params, values, strict=True)) for values in product(*choices)]


def _values(key: str, value: Any) -> list[Any]:
    return _nonempty(key, value) if isinstance(value, list) else [value]


def _nonempty[T](key: str, values: list[T]) -> list[T]:
    if not values:
        raise EmptyListError(f"{key} is an empty list, which expands into no runs")
    return values


def _name(part: str, params: Mapping[str, Any], chosen: Mapping[str, Any]) -> str:
    run = f"the {part} run"
    listed = ", ".join(
        f"{key}={chosen[key]!r}"
        for key, value in params.items()
        if isinstance(value, list)
    )
    return f"{run} with {listed}" if listed else run
