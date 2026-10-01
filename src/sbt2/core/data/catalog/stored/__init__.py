from sbt2.core.data.catalog.stored.candles import Candles
from sbt2.core.data.catalog.stored.funding import Funding
from sbt2.core.data.catalog.stored.mark_prices import MarkPrices
from sbt2.core.data.catalog.stored.stored_type import (
    Bounds,
    CatalogRoot,
    DayFile,
    StoredType,
    nautilus_type,
)
from sbt2.core.data.catalog.stored.trades import Trades

STORED: tuple[StoredType, ...] = (Trades(), MarkPrices(), Funding(), Candles())


class UnstoredDataTypeError(LookupError):
    """A data type sbt2 does not store in a catalog."""


def stored_type(data_type: type) -> StoredType:
    for each in STORED:
        if each.data_type is data_type:
            return each
    stored = ", ".join(each.data_type.__name__ for each in STORED)
    raise UnstoredDataTypeError(
        f"sbt2 stores no {data_type.__name__}; it stores {stored}"
    )


__all__ = [
    "STORED",
    "Bounds",
    "CatalogRoot",
    "DayFile",
    "StoredType",
    "UnstoredDataTypeError",
    "nautilus_type",
    "stored_type",
]
