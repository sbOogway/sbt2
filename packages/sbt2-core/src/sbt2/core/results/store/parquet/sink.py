import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model import PortfolioSnapshot, PositionAdjusted

from sbt2.core.data import Gap
from sbt2.core.results.metrics import (
    HeadlineMetrics,
    RunTables,
    Segment,
    headline_metrics,
)
from sbt2.core.results.store.parquet.tables import (
    carry_table,
    equity_table,
    write_table,
)
from sbt2.core.results.store.sink import IncompleteRunError, Reports
from sbt2.core.spec import ResolvedRunSpec

SUMMARY = "summary"

_UTC = pa.timestamp("ns", tz="UTC")
SUMMARY_SCHEMA = pa.schema(
    [
        ("run_id", pa.string()),
        ("batch_id", pa.string()),
        ("spec_hash", pa.string()),
        ("strategy", pa.string()),
        ("params", pa.string()),
        ("instruments", pa.list_(pa.string())),
        ("start", _UTC),
        ("end", _UTC),
        ("split", pa.string()),
        ("part", pa.string()),
        ("known_gaps", pa.list_(pa.string())),
        ("currency", pa.string()),
        *(
            (each.name, pa.int64() if each.type is int else pa.float64())
            for each in fields(HeadlineMetrics)
        ),
        ("drawdown_tripped_at", _UTC),
    ]
)


@dataclass(frozen=True)
class NewRun:
    run_id: str
    batch_id: str | None
    spec: ResolvedRunSpec
    known_gaps: tuple[Gap, ...]

    @property
    def segment(self) -> Segment:
        return Segment.of_run(self.spec)


class ParquetSink:
    def __init__(self, folder: Path, run: NewRun) -> None:
        self._folder = folder
        self._run = run
        self._tables: dict[str, pd.DataFrame] = {}
        self._drawdown_tripped_at: datetime | None = None

    @property
    def run_id(self) -> str:
        return self._run.run_id

    def write_equity(self, snapshots: Sequence[PortfolioSnapshot]) -> None:
        self._write("equity", equity_table(snapshots))

    def write_carry(self, adjustments: Sequence[PositionAdjusted]) -> None:
        self._write("carry", carry_table(adjustments))

    def write_reports(self, reports: Reports) -> None:
        self._write("fills", reports.fills)
        self._write("positions", reports.positions)
        self._write("account", reports.account)
        if reports.orders is not None:
            self._write("orders", reports.orders)

    def write_drawdown_trip(self, tripped_at: datetime) -> None:
        self._drawdown_tripped_at = tripped_at

    def finalize(self) -> None:
        metrics = headline_metrics(self._run_tables(), self._run.segment)
        row = _summary(self._run, metrics, self._drawdown_tripped_at)
        summary = pa.Table.from_pylist([row], SUMMARY_SCHEMA)
        pq.write_table(summary, self._folder / f"{SUMMARY}.parquet")

    def _write(self, name: str, frame: pd.DataFrame) -> None:
        write_table(frame, self._folder / f"{name}.parquet")
        self._tables[name] = frame

    def _run_tables(self) -> RunTables:
        missing = [
            name for name in ("equity", "carry", "fills") if name not in self._tables
        ]
        if missing:
            raise IncompleteRunError(
                f"run {self.run_id} finalized before writing {', '.join(missing)}"
            )
        return RunTables(
            equity=self._tables["equity"],
            fills=self._tables["fills"],
            carry=self._tables["carry"],
            currency=self._run.spec.currency,
        )


def _summary(
    run: NewRun, metrics: HeadlineMetrics, drawdown_tripped_at: datetime | None
) -> dict[str, object]:
    strategy = run.spec.strategy
    return {
        "run_id": run.run_id,
        "batch_id": run.batch_id,
        "spec_hash": run.spec.hash,
        "strategy": strategy.strategy,
        "params": json.dumps(dict(strategy.params), sort_keys=True, default=str),
        "instruments": [str(each) for each in strategy.instruments],
        "start": run.spec.start,
        "end": run.spec.end,
        "split": run.spec.split_json(),
        "part": run.spec.part,
        "known_gaps": [str(each) for each in run.known_gaps],
        "currency": run.spec.currency,
        **asdict(metrics),
        "drawdown_tripped_at": drawdown_tripped_at,
    }
