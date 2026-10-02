import math
from collections.abc import Mapping
from typing import Any

import pandas as pd
from google.protobuf.timestamp_pb2 import Timestamp

from sbt2.core import results as core
from sbt2.protocol.v1 import results_pb2 as wire


def run_filter(selected: wire.RunFilter) -> core.RunFilter:
    fields = {
        name: getattr(selected, name) if selected.HasField(name) else None
        for name in ("strategy", "part", "batch", "study")
    }
    ids = tuple(selected.run_ids.values) if selected.HasField("run_ids") else None
    return core.RunFilter(**fields, run_ids=ids)


def summary(row: Mapping[Any, Any]) -> wire.RunSummary:
    result = wire.RunSummary(
        run_id=row["run_id"],
        spec_hash=row["spec_hash"],
        strategy=row["strategy"],
        params_json=row["params"],
        instruments=list(row["instruments"]),
        start_at=_timestamp(row["start"]),
        end_at=_timestamp(row["end"]),
        split_json=row["split"],
        part=row["part"],
        known_gaps=list(row["known_gaps"]),
        currency=row["currency"],
        headline=_headline(row),
    )
    for name in ("batch_id", "study"):
        if not pd.isna(row[name]):
            setattr(result, name, row[name])
    if not pd.isna(row["drawdown_tripped_at"]):
        result.drawdown_tripped_at.CopyFrom(_timestamp(row["drawdown_tripped_at"]))
    return result


def _headline(row: Mapping[Any, Any]) -> wire.HeadlineMetrics:
    result = wire.HeadlineMetrics(
        trade_count=int(row["trade_count"]),
        total_fees=str(row["total_fees"]),
        total_carry=str(row["total_carry"]),
    )
    for name in ("net_return", "annualized_return", "sharpe", "max_drawdown"):
        value = row[name]
        if value is not None and not pd.isna(value) and math.isfinite(value):
            setattr(result, name, str(value))
    return result


def _timestamp(value: Any) -> Timestamp:
    result = Timestamp()
    result.FromNanoseconds(pd.Timestamp(value).value)
    return result
