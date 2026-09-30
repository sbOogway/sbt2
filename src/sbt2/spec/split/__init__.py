from collections.abc import Mapping
from dataclasses import fields
from typing import Any

from sbt2.spec.errors import SpecError
from sbt2.spec.split.dates import DateSplit, SplitDateError
from sbt2.spec.split.fractions import FractionSplit, SplitFractionError
from sbt2.spec.split.splitter import PARTS, Splitter

_SPLITTERS: tuple[type[Splitter], ...] = (FractionSplit, DateSplit)


class UnknownSplitError(SpecError):
    """A split table whose keys fit no splitter."""


def from_table(table: Mapping[str, Any]) -> Splitter:
    """The splitter whose arguments are exactly the table's keys."""
    for kind in _SPLITTERS:
        if set(table) == _arguments(kind):
            return kind(**table)
    forms = " or ".join(" and ".join(sorted(_arguments(k))) for k in _SPLITTERS)
    raise UnknownSplitError(
        f"split keys {', '.join(sorted(table))} fit no split; a split takes {forms}"
    )


def _arguments(kind: type[Splitter]) -> set[str]:
    return {each.name for each in fields(kind)}


__all__ = [
    "PARTS",
    "DateSplit",
    "FractionSplit",
    "SplitDateError",
    "SplitFractionError",
    "Splitter",
    "UnknownSplitError",
    "from_table",
]
