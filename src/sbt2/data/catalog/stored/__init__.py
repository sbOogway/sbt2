from sbt2.data.catalog.stored.candles import Candles
from sbt2.data.catalog.stored.funding import Funding
from sbt2.data.catalog.stored.mark_prices import MarkPrices
from sbt2.data.catalog.stored.stored_type import (
    Bounds,
    CatalogRoot,
    DayFile,
    StoredType,
)
from sbt2.data.catalog.stored.trades import Trades
from sbt2.data.sources import UnsupportedDataTypeError

STORED: tuple[StoredType, ...] = (Trades(), MarkPrices(), Funding(), Candles())


def stored_type(data_type: type) -> StoredType:
    for each in STORED:
        if each.data_type is data_type:
            return each
    stored = ", ".join(each.data_type.__name__ for each in STORED)
    raise UnsupportedDataTypeError(
        f"sbt2 stores no {data_type.__name__}; it stores {stored}"
    )


__all__ = [
    "STORED",
    "Bounds",
    "CatalogRoot",
    "DayFile",
    "StoredType",
    "stored_type",
]
