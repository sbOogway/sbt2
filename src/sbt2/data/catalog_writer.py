from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model import (
    FundingRateUpdate,
    InstrumentId,
    MarkPriceUpdate,
    NautilusDataType,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.serialization import get_arrow_schema_bytes

# Nautilus's own writers stage under "<file>#N"; its reader ignores such names.
_PARTIAL_SUFFIX = "#sbt2"

type Bounds = tuple[int, int]

_TYPED_WRITERS: Mapping[type, Callable[..., str]] = {
    TradeTick: ParquetDataCatalog.write_trade_ticks,
    MarkPriceUpdate: ParquetDataCatalog.write_mark_price_updates,
}

# Nautilus's directory for each type sbt2 writes itself, for funding (no Python
# writer) and for zero-row days (its writers write no file for an empty list).
_DIRECTORIES: Mapping[type, str] = {
    TradeTick: "trades",
    MarkPriceUpdate: "mark_prices",
    FundingRateUpdate: "funding_rates",
}


# The schema metadata nautilus's writers add, which its reader needs even when
# a file has no rows to take them from.
_METADATA: Mapping[type, tuple[str, ...]] = {
    TradeTick: ("price_precision", "size_precision"),
    MarkPriceUpdate: ("price_precision",),
    FundingRateUpdate: (),
}


@dataclass(frozen=True)
class DayFile:
    data_type: type
    instrument: Any
    bounds: Bounds


class CatalogWriter:
    """Writes whole files into a nautilus catalog; a file appears only once complete."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._catalog = ParquetDataCatalog(str(path))

    def has(self, day: DayFile) -> bool:
        intervals = self._catalog.get_intervals(
            _nautilus_type(day.data_type), str(day.instrument.id)
        )
        return day.bounds in intervals

    def write(self, day: DayFile, records: Sequence[Any]) -> None:
        if not records:
            self._write_table(day, _zero_rows(day))
        elif day.data_type is FundingRateUpdate:
            self._write_table(day, _funding_table(records))
        else:
            _TYPED_WRITERS[day.data_type](self._catalog, list(records), *day.bounds)

    def instrument(self, instrument_id: InstrumentId) -> Any | None:
        """The latest version of the instrument in the catalog, if any."""
        stored = self._catalog.instruments(instrument_ids=[str(instrument_id)])
        return max(stored, key=lambda each: each.ts_init, default=None)

    def write_instrument(self, instrument: Any) -> None:
        self._catalog.write_instruments([instrument])

    def remove(self, instrument_id: InstrumentId, data_types: Sequence[type]) -> None:
        """Every version of the instrument and all its ``data_types`` files."""
        for data_type in data_types:
            self._catalog.delete_data_range(
                _nautilus_type(data_type), str(instrument_id)
            )
        for each in self._catalog.list_parquet_files(
            NautilusDataType.Instrument, str(instrument_id)
        ):
            (self._path / each).unlink()

    def _write_table(self, day: DayFile, table: pa.Table) -> None:
        """Writes under a partial name and renames, as nautilus's writers do."""
        target = self._path / _relative_path(day)
        partial = target.with_name(target.name + _PARTIAL_SUFFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, partial)
        partial.replace(target)


def _nautilus_type(data_type: type) -> NautilusDataType:
    return getattr(NautilusDataType, data_type.__name__)


def _zero_rows(day: DayFile) -> pa.Table:
    schema = _arrow_schema(day.data_type)
    metadata = {**(schema.metadata or {}), **_metadata(day)}
    return schema.with_metadata(metadata).empty_table()


def _metadata(day: DayFile) -> dict[str, str]:
    instrument = day.instrument
    precisions = {
        name: str(getattr(instrument, name)) for name in _METADATA[day.data_type]
    }
    return {"instrument_id": str(instrument.id), **precisions}


def _relative_path(day: DayFile) -> Path:
    return Path(
        "data",
        _DIRECTORIES[day.data_type],
        str(day.instrument.id),
        _file_name(day.bounds),
    )


def _file_name(bounds: Bounds) -> str:
    return "_".join(_file_timestamp(ts) for ts in bounds) + ".parquet"


def _file_timestamp(ts: int) -> str:
    seconds, nanos = divmod(ts, 1_000_000_000)
    moment = datetime.fromtimestamp(seconds, UTC)
    return f"{moment:%Y-%m-%dT%H-%M-%S}-{nanos:09d}Z"


def _arrow_schema(data_type: type) -> pa.Schema:
    return pa.ipc.read_schema(pa.py_buffer(get_arrow_schema_bytes(data_type)))


def _funding_table(fundings: Sequence[FundingRateUpdate]) -> pa.Table:
    columns = {
        "instrument_id": [str(each.instrument_id) for each in fundings],
        "rate": [str(each.rate) for each in fundings],
        "interval": [each.interval for each in fundings],
        "next_funding_ns": [each.next_funding_ns for each in fundings],
        "ts_event": [each.ts_event for each in fundings],
        "ts_init": [each.ts_init for each in fundings],
        "identifier": [str(each.instrument_id) for each in fundings],
    }
    return pa.table(columns, schema=_arrow_schema(FundingRateUpdate))
