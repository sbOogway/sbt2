from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from kit import DAY, INSTRUMENT_ID, START
from nautilus_trader.model import FundingRateUpdate
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.serialization import get_arrow_schema_bytes

Bounds = tuple[int, int]


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
    directory = path / "data" / "funding_rates" / str(INSTRUMENT_ID)
    directory.mkdir(parents=True, exist_ok=True)
    file = directory / catalog_file_name(bounds)
    pq.write_table(_funding_table(fundings), file)
    return file


def _funding_table(fundings: Sequence[FundingRateUpdate]) -> pa.Table:
    schema = pa.ipc.read_schema(pa.py_buffer(get_arrow_schema_bytes(FundingRateUpdate)))
    columns = {
        "instrument_id": [str(funding.instrument_id) for funding in fundings],
        "rate": [str(funding.rate) for funding in fundings],
        "interval": [funding.interval for funding in fundings],
        "next_funding_ns": [funding.next_funding_ns for funding in fundings],
        "ts_event": [funding.ts_event for funding in fundings],
        "ts_init": [funding.ts_init for funding in fundings],
        "identifier": [str(funding.instrument_id) for funding in fundings],
    }
    return pa.table(columns, schema=schema)
