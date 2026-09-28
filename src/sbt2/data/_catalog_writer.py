import shutil
import uuid
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

STAGING = ".staging"

type Bounds = tuple[int, int]
type _Write = Callable[[Path], Sequence[str]]

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
    """Writes whole files into a nautilus catalog, each staged and then moved in."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._catalog = ParquetDataCatalog(str(path))
        shutil.rmtree(path / STAGING, ignore_errors=True)

    def has(self, day: DayFile) -> bool:
        intervals = self._catalog.get_intervals(
            _nautilus_type(day.data_type), str(day.instrument.id)
        )
        return day.bounds in intervals

    def write(self, day: DayFile, records: Sequence[Any]) -> None:
        if not records:
            self._staged(lambda root: [_write_zero_rows(root, day)])
        elif day.data_type is FundingRateUpdate:
            self._staged(lambda root: [_write_funding(root, day, records)])
        else:
            self._staged(lambda root: [_write_typed(root, day, records)])

    def instrument(self, instrument_id: InstrumentId) -> Any | None:
        """The latest version of the instrument in the catalog, if any."""
        stored = self._catalog.instruments(instrument_ids=[str(instrument_id)])
        return max(stored, key=lambda each: each.ts_init, default=None)

    def write_instrument(self, instrument: Any) -> None:
        self._staged(
            lambda root: _catalog(root).write_instruments([instrument]),
        )

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

    def _staged(self, write: _Write) -> None:
        """Runs ``write`` into a fresh staging root, then moves its files in."""
        root = self._path / STAGING / uuid.uuid4().hex
        root.mkdir(parents=True)
        try:
            for relative in write(root):
                target = self._path / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                (root / relative).replace(target)
        finally:
            shutil.rmtree(root)


def _catalog(root: Path) -> ParquetDataCatalog:
    return ParquetDataCatalog(str(root))


def _nautilus_type(data_type: type) -> NautilusDataType:
    return getattr(NautilusDataType, data_type.__name__)


def _write_typed(root: Path, day: DayFile, records: Sequence[Any]) -> str:
    writer = _TYPED_WRITERS[day.data_type]
    return writer(_catalog(root), list(records), *day.bounds)


def _write_zero_rows(root: Path, day: DayFile) -> str:
    schema = _arrow_schema(day.data_type)
    metadata = {**(schema.metadata or {}), **_metadata(day)}
    return _write_table(root, day, schema.with_metadata(metadata).empty_table())


def _metadata(day: DayFile) -> dict[str, str]:
    instrument = day.instrument
    precisions = {
        name: str(getattr(instrument, name)) for name in _METADATA[day.data_type]
    }
    return {"instrument_id": str(instrument.id), **precisions}


def _write_funding(
    root: Path, day: DayFile, fundings: Sequence[FundingRateUpdate]
) -> str:
    return _write_table(root, day, _funding_table(fundings))


def _write_table(root: Path, day: DayFile, table: pa.Table) -> str:
    relative = Path(
        "data",
        _DIRECTORIES[day.data_type],
        str(day.instrument.id),
        _file_name(day.bounds),
    )
    (root / relative).parent.mkdir(parents=True)
    pq.write_table(table, root / relative)
    return str(relative)


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
