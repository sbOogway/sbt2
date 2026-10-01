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


def source(name: str, config: Path) -> Source:
    """The source adapter called ``name``, built from its table in ``config``."""
    return _source_class(name).from_config(_tables(config).get(name, {}))


def known_gaps(config: Path) -> frozenset[Gap]:
    """The known gaps of every source with a table in ``config``."""
    names = _tables(config)
    return frozenset().union(*(source(name, config).known_gaps for name in names))


def _source_class(name: str) -> type[Source]:
    for each in _SOURCES:
        if each.name == name:
            return each
    known = ", ".join(sorted(each.name for each in _SOURCES))
    raise UnknownSourceError(f"no source {name}; known: {known}")


def _tables(config: Path) -> dict[str, Any]:
    with config.open("rb") as file:
        return tomllib.load(file)
