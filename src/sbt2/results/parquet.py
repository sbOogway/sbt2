import json
import shutil
import uuid
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model import Money, PortfolioSnapshot, PositionAdjusted

from sbt2.results.metrics import HeadlineMetrics, RunTables, Segment, headline_metrics
from sbt2.results.sink import IncompleteRunError, OutputSink, Reports
from sbt2.results.store import MissingTableError, Provenance, Table, UnknownRunError
from sbt2.results.tables import carry_table, equity_table, read_table, write_table
from sbt2.spec import ResolvedRunSpec

RESULTS = Path("data/results")
SUMMARY = "summary"

_UTC = pa.timestamp("ns", tz="UTC")
_SUMMARY_SCHEMA = pa.schema(
    [
        ("run_id", pa.string()),
        ("spec_hash", pa.string()),
        ("strategy", pa.string()),
        ("params", pa.string()),
        ("instruments", pa.list_(pa.string())),
        ("start", _UTC),
        ("end", _UTC),
        ("split", pa.string()),
        ("part", pa.string()),
        ("git_sha", pa.string()),
        ("git_dirty", pa.bool_()),
        ("data_fingerprint", pa.string()),
        ("known_gaps", pa.list_(pa.string())),
        ("currency", pa.string()),
        ("net_return", pa.float64()),
        ("annualized_return", pa.float64()),
        ("sharpe", pa.float64()),
        ("max_drawdown", pa.float64()),
        ("alpha", pa.float64()),
        ("beta", pa.float64()),
        ("trade_count", pa.int64()),
        ("total_fees", pa.float64()),
        ("total_carry", pa.float64()),
    ]
)


class ParquetResultStore:
    """Each run is a folder of parquet tables under ``root/runs/{run_id}``."""

    def __init__(self, root: Path = RESULTS) -> None:
        self._runs = root / "runs"

    def new_run(self, spec: ResolvedRunSpec, provenance: Provenance) -> OutputSink:
        run = _Run(str(uuid.uuid7()), spec, provenance)
        folder = self._runs / run.run_id
        folder.mkdir(parents=True)
        (folder / "spec.json").write_text(spec.to_json())
        return _ParquetSink(folder, run)

    def runs(self) -> pd.DataFrame:
        paths = sorted(self._runs.glob(f"*/{SUMMARY}.parquet"))
        if not paths:
            return _SUMMARY_SCHEMA.empty_table().to_pandas()
        return pd.concat([read_table(path) for path in paths], ignore_index=True)

    def load(self, run_id: str, table: Table) -> pd.DataFrame:
        path = self._folder(run_id) / f"{table}.parquet"
        if not path.exists():
            raise MissingTableError(f"run {run_id} has no {table} table")
        return read_table(path)

    def delete(self, run_id: str) -> None:
        shutil.rmtree(self._folder(run_id))

    def _folder(self, run_id: str) -> Path:
        folder = self._runs / _canonical_uuid(run_id)
        if not folder.is_dir():
            raise UnknownRunError(f"no run {run_id} in {self._runs}")
        return folder


@dataclass(frozen=True)
class _Run:
    run_id: str
    spec: ResolvedRunSpec
    provenance: Provenance

    @property
    def currency(self) -> str:
        [balance] = self.spec.venue["starting_balances"]
        return Money.from_str(balance).currency.code

    @property
    def segment(self) -> Segment:
        return Segment(
            self.spec.start,
            self.spec.end,
            timedelta(milliseconds=self.spec.equity_interval_ms),
            self.spec.asset.days_per_year,
        )


class _ParquetSink:
    def __init__(self, folder: Path, run: _Run) -> None:
        self._folder = folder
        self._run = run
        self._tables: dict[str, pd.DataFrame] = {}

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

    def finalize(self, benchmark: pd.Series | None = None) -> None:
        metrics = headline_metrics(self._run_tables(), self._run.segment, benchmark)
        summary = pa.Table.from_pylist([_summary(self._run, metrics)], _SUMMARY_SCHEMA)
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
            currency=self._run.currency,
        )


def _summary(run: _Run, metrics: HeadlineMetrics) -> dict[str, object]:
    strategy = run.spec.strategy
    return {
        "run_id": run.run_id,
        "spec_hash": run.spec.hash,
        "strategy": strategy.strategy,
        "params": json.dumps(dict(strategy.params), sort_keys=True, default=str),
        "instruments": [str(each) for each in strategy.instruments],
        "start": run.spec.start,
        "end": run.spec.end,
        "split": run.spec.split_json(),
        "part": run.spec.part,
        **_provenance(run.provenance),
        "currency": run.currency,
        **asdict(metrics),
    }


def _provenance(provenance: Provenance) -> dict[str, object]:
    return {
        "git_sha": provenance.git_sha,
        "git_dirty": provenance.git_dirty,
        "data_fingerprint": provenance.data_fingerprint,
        "known_gaps": [str(each) for each in provenance.known_gaps],
    }


def _canonical_uuid(run_id: str) -> str:
    """Guards the store against run ids that would reach outside it."""
    try:
        return str(uuid.UUID(run_id))
    except ValueError:
        raise UnknownRunError(f"{run_id!r} is not a run id") from None
