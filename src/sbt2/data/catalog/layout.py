"""How nautilus lays out a catalog on disk, for the data types sbt2 stores."""

from collections.abc import Mapping
from datetime import UTC, datetime

from nautilus_trader.model import (
    Bar,
    BarType,
    FundingRateUpdate,
    InstrumentId,
    MarkPriceUpdate,
    NautilusDataType,
    TradeTick,
)

from sbt2.data.sources import candle_type

type Bounds = tuple[int, int]

_DIRECTORIES: Mapping[type, str] = {
    TradeTick: "trades",
    MarkPriceUpdate: "mark_prices",
    FundingRateUpdate: "funding_rates",
    Bar: "bars",
}


def nautilus_type(data_type: type) -> NautilusDataType:
    return getattr(NautilusDataType, data_type.__name__)


def directory(data_type: type) -> str:
    return _DIRECTORIES[data_type]


def identifier(data_type: type, instrument_id: InstrumentId) -> str:
    """The name nautilus files an instrument's data under: bars go by bar type."""
    if data_type is Bar:
        return str(candle_type(instrument_id))
    return str(instrument_id)


def instrument_id(data_type: type, identifier: str) -> InstrumentId:
    """The inverse of ``identifier``."""
    if data_type is Bar:
        return BarType.from_str(identifier).instrument_id
    return InstrumentId.from_str(identifier)


def file_name(bounds: Bounds) -> str:
    return "_".join(_file_timestamp(ts) for ts in bounds) + ".parquet"


def _file_timestamp(ts: int) -> str:
    seconds, nanos = divmod(ts, 1_000_000_000)
    moment = datetime.fromtimestamp(seconds, UTC)
    return f"{moment:%Y-%m-%dT%H-%M-%S}-{nanos:09d}Z"
