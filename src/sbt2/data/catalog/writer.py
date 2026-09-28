from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model import (
    Bar,
    FundingRateUpdate,
    InstrumentId,
    MarkPriceUpdate,
    NautilusDataType,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.serialization import get_arrow_schema_bytes

from sbt2.data.catalog import layout

# Nautilus's own writers stage under "<file>#N"; its reader ignores such names.
_PARTIAL_SUFFIX = "#sbt2"

_TYPED_WRITERS: Mapping[type, Callable[..., str]] = {
    TradeTick: ParquetDataCatalog.write_trade_ticks,
    MarkPriceUpdate: ParquetDataCatalog.write_mark_price_updates,
    Bar: ParquetDataCatalog.write_bars,
}


# The schema metadata nautilus's writers add, which its reader needs even when
# a file has no rows to take them from.
_METADATA: Mapping[type, tuple[str, ...]] = {
    TradeTick: ("price_precision", "size_precision"),
    MarkPriceUpdate: ("price_precision",),
    FundingRateUpdate: (),
    Bar: ("price_precision", "size_precision"),
}


@dataclass(frozen=True)
class DayFile:
    data_type: type
    instrument: Any
    bounds: layout.Bounds

    @property
    def identifier(self) -> str:
        return layout.identifier(self.data_type, self.instrument.id)


class CatalogWriter:
    """Writes whole files into a nautilus catalog; a file appears only once complete."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._catalog = ParquetDataCatalog(str(path))

    def has(self, day: DayFile) -> bool:
        intervals = self._catalog.get_intervals(
            layout.nautilus_type(day.data_type), day.identifier
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
                layout.nautilus_type(data_type),
                layout.identifier(data_type, instrument_id),
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


def _zero_rows(day: DayFile) -> pa.Table:
    schema = _arrow_schema(day.data_type)
    metadata = {**(schema.metadata or {}), **_metadata(day)}
    return schema.with_metadata(metadata).empty_table()


def _metadata(day: DayFile) -> dict[str, str]:
    instrument = day.instrument
    precisions = {
        name: str(getattr(instrument, name)) for name in _METADATA[day.data_type]
    }
    names = {"instrument_id": str(instrument.id)}
    if day.data_type is Bar:
        names["bar_type"] = day.identifier
    return {**names, **precisions}


# sbt2 writes funding (nautilus has no Python writer) and zero-row days (its
# writers write no file for an empty list) itself, where nautilus would.
def _relative_path(day: DayFile) -> Path:
    return Path(
        "data",
        layout.directory(day.data_type),
        day.identifier,
        layout.file_name(day.bounds),
    )


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
