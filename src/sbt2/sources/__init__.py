import tomllib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from sbt2.sources.base import (
    Fetch,
    FundingOffGridError,
    Gap,
    MissingAtSourceError,
    RawFile,
    Source,
    UnsupportedDataTypeError,
)
from sbt2.sources.bybit import BybitSource

__all__ = [
    "Fetch",
    "FundingOffGridError",
    "Gap",
    "MissingAtSourceError",
    "RawFile",
    "Source",
    "UnknownSourceError",
    "UnsupportedDataTypeError",
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
    with config.open("rb") as file:
        return factory(tomllib.load(file).get(name, {}))
