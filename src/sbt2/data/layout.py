"""How nautilus lays out a catalog on disk, for the data types sbt2 stores."""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from nautilus_trader.model import (
    FundingRateUpdate,
    MarkPriceUpdate,
    NautilusDataType,
    TradeTick,
)

type Bounds = tuple[int, int]

_DIRECTORIES: Mapping[type, str] = {
    TradeTick: "trades",
    MarkPriceUpdate: "mark_prices",
    FundingRateUpdate: "funding_rates",
}


def nautilus_type(data_type: type) -> NautilusDataType:
    return getattr(NautilusDataType, data_type.__name__)


def directory(data_type: type) -> str:
    return _DIRECTORIES[data_type]


def file_name(bounds: Bounds) -> str:
    return "_".join(_file_timestamp(ts) for ts in bounds) + ".parquet"


def file_bounds(name: str) -> Bounds:
    """The bounds nautilus encodes in a data file's name."""
    first, last = Path(name).stem.split("_")
    return _parsed_timestamp(first), _parsed_timestamp(last)


def _file_timestamp(ts: int) -> str:
    seconds, nanos = divmod(ts, 1_000_000_000)
    moment = datetime.fromtimestamp(seconds, UTC)
    return f"{moment:%Y-%m-%dT%H-%M-%S}-{nanos:09d}Z"


def _parsed_timestamp(text: str) -> int:
    moment, nanos = text[:19], text[20:29]
    seconds = datetime.strptime(moment, "%Y-%m-%dT%H-%M-%S").replace(tzinfo=UTC)
    return int(seconds.timestamp()) * 1_000_000_000 + int(nanos)
