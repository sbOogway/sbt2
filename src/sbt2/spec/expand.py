from collections.abc import Mapping
from typing import Any

_UNNAMED_PARTS = ("train", "validation")


def expand(table: Mapping[str, Any]) -> list[dict[str, Any]]:
    """One table per run a spec file's table describes.

    Without ``part``, a spec runs its train and validation parts; test must be
    asked for.
    """
    return [{**table, "part": part} for part in _parts(table.get("part"))]


def _parts(part: str | list[str] | None) -> list[str]:
    if part is None:
        return list(_UNNAMED_PARTS)
    if isinstance(part, str):
        return [part]
    return part
