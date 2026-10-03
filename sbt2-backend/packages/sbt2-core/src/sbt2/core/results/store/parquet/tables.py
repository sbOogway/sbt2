import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model import PortfolioSnapshot, PositionAdjusted

_JSON_COLUMNS = b"sbt2.json_columns"
_TIMESTAMPS = ("ts_event", "ts_init")


def equity_table(snapshots: Iterable[PortfolioSnapshot]) -> pd.DataFrame:
    """One row per snapshot and currency of its total equity."""
    rows = [
        {
            "ts_event": snapshot.ts_event,
            "account_id": str(snapshot.account_id),
            "currency": money.currency.code,
            "total_equity": money.as_double(),
        }
        for snapshot in snapshots
        for money in snapshot.total_equity
    ]
    columns = ["ts_event", "account_id", "currency", "total_equity"]
    return _with_timestamps(pd.DataFrame(rows, columns=columns))


def carry_table(adjustments: Iterable[PositionAdjusted]) -> pd.DataFrame:
    """Nautilus's own fields of each adjustment, one row each, in time order
    and by instrument within the same time."""
    ordered = sorted(
        adjustments, key=lambda each: (each.ts_event, str(each.instrument_id))
    )
    return _with_timestamps(pd.DataFrame([each.to_dict() for each in ordered]))


def write_table(frame: pd.DataFrame, path: Path) -> None:
    """Write ``frame`` as parquet, nested columns as JSON text.

    Parquet can't hold some of nautilus's nested report values, such as an
    empty ``info`` dict, so they are encoded and decoded again on read.
    """
    nested = [str(name) for name, column in frame.items() if _is_nested(column)]
    encoded = frame.assign(**{column: frame[column].map(_to_json) for column in nested})
    table = pa.Table.from_pandas(encoded)
    metadata = {**(table.schema.metadata or {}), _JSON_COLUMNS: json.dumps(nested)}
    pq.write_table(table.replace_schema_metadata(metadata), path)


def read_table(path: Path) -> pd.DataFrame:
    table = pq.read_table(path)
    nested = json.loads((table.schema.metadata or {}).get(_JSON_COLUMNS, b"[]"))
    frame = table.to_pandas()
    return frame.assign(**{column: frame[column].map(_from_json) for column in nested})


def _with_timestamps(frame: pd.DataFrame) -> pd.DataFrame:
    present = [column for column in _TIMESTAMPS if column in frame.columns]
    return frame.assign(
        **{
            column: pd.to_datetime(frame[column], unit="ns", utc=True)
            for column in present
        }
    )


def _is_nested(column: pd.Series) -> bool:
    return column.dtype == object and any(
        isinstance(value, dict | list | tuple) for value in column
    )


def _to_json(value: Any) -> str | None:
    if value is None or value is pd.NA:
        return None
    return json.dumps(value, default=str)


def _from_json(value: str | float | None) -> Any:
    return json.loads(value) if isinstance(value, str) else None
