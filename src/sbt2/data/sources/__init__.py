import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sbt2.data.sources.base import (
    CANDLES,
    Fetch,
    FundingOffGridError,
    Gap,
    MissingAtSourceError,
    RawFile,
    Source,
    UnsupportedDataTypeError,
    candle_type,
    data_types,
    is_known_gap,
)
from sbt2.data.sources.bybit import BybitSource

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
    "data_types",
    "is_known_gap",
    "known_gaps",
    "source",
]

_FACTORIES: Mapping[str, Callable[[Mapping[str, Any]], Source]] = {
    "bybit": BybitSource.from_config,
}


class UnknownSourceError(LookupError):
    pass


def source(name: str, config: Path) -> Source:
    """The source adapter called ``name``, built from its table in ``config``."""
    try:
        factory = _FACTORIES[name]
    except KeyError:
        raise UnknownSourceError(
            f"no source {name}; known: {', '.join(sorted(_FACTORIES))}"
        ) from None
    return factory(_tables(config).get(name, {}))


def known_gaps(config: Path) -> frozenset[Gap]:
    """The known gaps of every source with a table in ``config``."""
    names = _tables(config)
    return frozenset().union(*(source(name, config).known_gaps for name in names))


def _tables(config: Path) -> dict[str, Any]:
    with config.open("rb") as file:
        return tomllib.load(file)
