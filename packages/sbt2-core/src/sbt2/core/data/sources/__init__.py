import tomllib
from pathlib import Path
from typing import Any

from sbt2.core.data.sources.base import (
    CANDLES,
    Fetch,
    FundingOffGridError,
    Gap,
    MissingAtSourceError,
    RawFile,
    Source,
    UnsupportedDataTypeError,
    candle_type,
)
from sbt2.core.data.sources.bybit import BybitSource

__all__ = [
    "CANDLES",
    "Fetch",
    "FundingOffGridError",
    "Gap",
    "MissingAtSourceError",
    "RawFile",
    "Source",
    "UnknownSourceError",
    "UnsupportedDataTypeError",
    "candle_type",
    "known_gaps",
    "source",
]

_SOURCES: tuple[type[Source], ...] = (BybitSource,)


class UnknownSourceError(LookupError):
    pass


def source(name: str, known_gaps_file: Path) -> Source:
    """The source adapter called ``name``, with the known gaps
    ``known_gaps_file`` lists for it."""
    return _source_class(name).listing(_lists(known_gaps_file).get(name, ()))


def known_gaps(known_gaps_file: Path) -> frozenset[Gap]:
    """The known gaps of every source ``known_gaps_file`` lists; none when the
    file is missing."""
    names = _lists(known_gaps_file)
    return frozenset().union(
        *(source(name, known_gaps_file).known_gaps for name in names)
    )


def _source_class(name: str) -> type[Source]:
    for each in _SOURCES:
        if each.name == name:
            return each
    known = ", ".join(sorted(each.name for each in _SOURCES))
    raise UnknownSourceError(f"no source {name}; known: {known}")


def _lists(known_gaps_file: Path) -> dict[str, Any]:
    if not known_gaps_file.exists():
        return {}
    with known_gaps_file.open("rb") as file:
        return tomllib.load(file)
