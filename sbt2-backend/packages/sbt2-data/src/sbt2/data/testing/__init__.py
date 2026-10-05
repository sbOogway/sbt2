"""Test doubles for code built on ``sbt2.data``: a catalog writer and a served source."""

from sbt2.data.catalog import CatalogWriter, DayFile
from sbt2.data.sources import MissingAtSourceError, RawFile
from sbt2.data.testing.served import (
    INSTRUMENT_ID,
    SYMBOL,
    ServedSource,
    perpetual,
    spot_pair,
)

__all__ = [
    "INSTRUMENT_ID",
    "SYMBOL",
    "CatalogWriter",
    "DayFile",
    "MissingAtSourceError",
    "RawFile",
    "ServedSource",
    "perpetual",
    "spot_pair",
]
