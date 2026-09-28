from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from kit import DAY, INSTRUMENT_ID, START
from nautilus_trader.model import FundingRateUpdate, MarkPriceUpdate, TradeTick
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.serialization import get_arrow_schema_bytes

Bounds = tuple[int, int]

_DIRECTORIES: dict[type, str] = {
    TradeTick: "trades",
    MarkPriceUpdate: "mark_prices",
    FundingRateUpdate: "funding_rates",
}


def day_bounds(day: int) -> Bounds:
    start = START + day * DAY
    return start, start + DAY - 1


def new_catalog(path: Path) -> ParquetDataCatalog:
    path.mkdir(parents=True, exist_ok=True)
    return ParquetDataCatalog(str(path))


def catalog_file_name(bounds: Bounds) -> str:
    return "_".join(_catalog_timestamp(ts) for ts in bounds) + ".parquet"


def _catalog_timestamp(ts: int) -> str:
    seconds, nanos = divmod(ts, 1_000_000_000)
    moment = datetime.fromtimestamp(seconds, UTC)
    return f"{moment:%Y-%m-%dT%H-%M-%S}-{nanos:09d}Z"


def write_funding(
    path: Path, fundings: Sequence[FundingRateUpdate], bounds: Bounds
) -> Path:
    file = _data_file(path, FundingRateUpdate, bounds)
    pq.write_table(_funding_table(fundings), file)
    return file


def write_zero_rows(path: Path, data_type: type, bounds: Bounds) -> Path:
    file = _data_file(path, data_type, bounds)
    pq.write_table(_arrow_schema(data_type).empty_table(), file)
    return file


def _data_file(path: Path, data_type: type, bounds: Bounds) -> Path:
    directory = path / "data" / _DIRECTORIES[data_type] / str(INSTRUMENT_ID)
    directory.mkdir(parents=True, exist_ok=True)
    return directory / catalog_file_name(bounds)


def _arrow_schema(data_type: type) -> pa.Schema:
    return pa.ipc.read_schema(pa.py_buffer(get_arrow_schema_bytes(data_type)))


def _funding_table(fundings: Sequence[FundingRateUpdate]) -> pa.Table:
    columns = {
        "instrument_id": [str(funding.instrument_id) for funding in fundings],
        "rate": [str(funding.rate) for funding in fundings],
        "interval": [funding.interval for funding in fundings],
        "next_funding_ns": [funding.next_funding_ns for funding in fundings],
        "ts_event": [funding.ts_event for funding in fundings],
        "ts_init": [funding.ts_init for funding in fundings],
        "identifier": [str(funding.instrument_id) for funding in fundings],
    }
    return pa.table(columns, schema=_arrow_schema(FundingRateUpdate))
