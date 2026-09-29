from collections.abc import Mapping
from itertools import product
from typing import Any

_UNNAMED_PARTS = ("train", "validation")


def expand(table: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One table per run a spec file's table describes.

    Without ``part``, a spec runs its train and validation parts; test must be
    asked for. Lists in ``params`` expand into their Cartesian product, in the
    order the file gives them.
    """
    return [
        {**table, "part": part, "params": params}
        for part in _parts(table.get("part"))
        for params in _combinations(table.get("params", {}))
    ]


def _parts(part: str | list[str] | None) -> list[str]:
    if part is None:
        return list(_UNNAMED_PARTS)
    if isinstance(part, str):
        return [part]
    return part


def _combinations(params: Mapping[str, Any]) -> list[dict[str, Any]]:
    choices = [_values(value) for value in params.values()]
    return [dict(zip(params, values, strict=True)) for values in product(*choices)]


def _values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else [value]
