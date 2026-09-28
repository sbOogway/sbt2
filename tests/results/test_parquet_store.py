import subprocess
import uuid
from pathlib import Path

import pandas as pd
import pytest
from nautilus_run import END, START, RunOutput, round_trip_with_funding, spec

from sbt2.results import (
    IncompleteRunError,
    MissingTableError,
    OutputSink,
    ParquetResultStore,
    Provenance,
    Reports,
    UnknownRunError,
)

PROVENANCE = Provenance(git_sha="abc123", git_dirty=False)


@pytest.fixture(scope="module")
def output() -> RunOutput:
    return round_trip_with_funding()


@pytest.fixture
def store(tmp_path: Path) -> ParquetResultStore:
    return ParquetResultStore(tmp_path)


def write(sink: OutputSink, output: RunOutput) -> None:
    sink.write_equity(output.snapshots)
    sink.write_carry(output.carry)
    sink.write_reports(output.reports)


def finished_run(
    store: ParquetResultStore, output: RunOutput, benchmark: pd.Series | None = None
) -> str:
    sink = store.new_run(spec(), PROVENANCE)
    write(sink, output)
    sink.finalize(benchmark)
    return sink.run_id


def test_run_ids_are_time_sortable_uuid7(store: ParquetResultStore) -> None:
    first = store.new_run(spec(), PROVENANCE).run_id
    second = store.new_run(spec(), PROVENANCE).run_id

    assert uuid.UUID(first).version == 7
    assert first < second


def test_a_run_writes_its_tables_spec_and_summary_into_its_folder(
    store: ParquetResultStore, output: RunOutput, tmp_path: Path
) -> None:
    run_id = finished_run(store, output)

    assert sorted(path.name for path in (tmp_path / "runs" / run_id).iterdir()) == [
        "account.parquet",
        "carry.parquet",
        "equity.parquet",
        "fills.parquet",
        "orders.parquet",
        "positions.parquet",
        "spec.json",
        "summary.parquet",
    ]
    assert (tmp_path / "runs" / run_id / "spec.json").read_text() == spec().to_json()


def test_summary_holds_the_run_provenance_and_headline_metrics(
    store: ParquetResultStore, output: RunOutput
) -> None:
    run_id = finished_run(store, output)

    [summary] = store.runs().to_dict("records")
    assert summary["run_id"] == run_id
    assert summary["spec_hash"] == spec().hash
    assert summary["strategy"] == "toy:RoundTrip"
    assert summary["params"] == '{"lots": 1}'
    assert list(summary["instruments"]) == ["BTCUSDT-LINEAR.BYBIT"]
    assert (summary["start"], summary["end"]) == (START, END)
    assert (summary["git_sha"], summary["git_dirty"]) == ("abc123", False)
    assert summary["currency"] == "USDT"
    assert summary["trade_count"] == 2
    assert summary["total_fees"] == pytest.approx(2.0)
    assert summary["total_carry"] == pytest.approx(-5.0)
    assert summary["net_return"] == pytest.approx(993 / 10_000)
    assert summary["max_drawdown"] <= 0
    assert pd.isna(summary["alpha"]) and pd.isna(summary["beta"])


def test_fields_later_milestones_fill_are_null(
    store: ParquetResultStore, output: RunOutput
) -> None:
    finished_run(store, output)

    [summary] = store.runs().to_dict("records")
    assert all(
        pd.isna(summary[field]) for field in ("data_fingerprint", "split", "segment")
    )


def test_a_benchmark_gives_alpha_and_beta(
    store: ParquetResultStore, output: RunOutput
) -> None:
    days = pd.date_range(START, periods=3, freq="12h", tz="UTC")
    finished_run(store, output, pd.Series([0.01, -0.02, 0.015], index=days))

    [summary] = store.runs().to_dict("records")
    assert not pd.isna(summary["alpha"]) and not pd.isna(summary["beta"])


def test_nautilus_reports_load_back_with_their_own_columns(
    store: ParquetResultStore, output: RunOutput
) -> None:
    run_id = finished_run(store, output)

    for table, report in [
        ("fills", output.reports.fills),
        ("positions", output.reports.positions),
        ("account", output.reports.account),
        ("orders", output.reports.orders),
    ]:
        assert report is not None
        loaded = store.load(run_id, table)
        assert list(loaded.columns) == list(report.columns)
        assert loaded.index.equals(report.index)


def test_nested_report_values_survive_the_round_trip(
    store: ParquetResultStore, output: RunOutput
) -> None:
    run_id = finished_run(store, output)

    account = store.load(run_id, "account")
    positions = store.load(run_id, "positions")
    assert list(account["info"]) == list(output.reports.account["info"])
    assert list(positions["trade_ids"]) == list(output.reports.positions["trade_ids"])


def test_equity_and_carry_come_from_nautilus(
    store: ParquetResultStore, output: RunOutput
) -> None:
    run_id = finished_run(store, output)

    equity = store.load(run_id, "equity")
    [funding] = store.load(run_id, "carry").to_dict("records")
    assert len(equity) == len(output.snapshots)
    assert equity["total_equity"].iloc[-1] == pytest.approx(10_993.0)
    assert equity["ts_event"].iloc[0] == START
    assert funding["adjustment_type"] == "FUNDING"
    assert funding["pnl_change"] == "-5.00000000 USDT"
    assert funding["ts_event"] == START + pd.Timedelta(hours=8)


def test_orders_are_optional(store: ParquetResultStore, output: RunOutput) -> None:
    sink = store.new_run(spec(), PROVENANCE)
    reports = output.reports
    without_orders = Reports(reports.fills, reports.positions, reports.account)
    write(sink, RunOutput(output.snapshots, output.carry, without_orders))
    sink.finalize()

    with pytest.raises(MissingTableError, match="orders"):
        store.load(sink.run_id, "orders")


def test_a_run_without_funding_or_fills_finalizes(
    store: ParquetResultStore, output: RunOutput
) -> None:
    sink = store.new_run(spec(), PROVENANCE)
    sink.write_equity(output.snapshots)
    sink.write_carry([])
    sink.write_reports(Reports(pd.DataFrame(), pd.DataFrame(), output.reports.account))
    sink.finalize()

    [summary] = store.runs().to_dict("records")
    assert (summary["trade_count"], summary["total_carry"]) == (0, 0.0)


def test_an_unfinished_run_is_not_listed_but_keeps_its_folder(
    store: ParquetResultStore, output: RunOutput
) -> None:
    sink = store.new_run(spec(), PROVENANCE)
    write(sink, output)

    assert store.runs().empty
    assert len(store.load(sink.run_id, "equity")) == len(output.snapshots)


def test_empty_store_lists_no_runs_with_summary_columns(
    store: ParquetResultStore,
) -> None:
    runs = store.runs()

    assert runs.empty
    assert {"run_id", "spec_hash", "net_return"} <= set(runs.columns)


def test_finalize_before_writing_everything_fails(
    store: ParquetResultStore, output: RunOutput
) -> None:
    sink = store.new_run(spec(), PROVENANCE)
    sink.write_equity(output.snapshots)

    with pytest.raises(IncompleteRunError, match="carry, fills"):
        sink.finalize()


def test_delete_removes_the_run(store: ParquetResultStore, output: RunOutput) -> None:
    run_id = finished_run(store, output)

    store.delete(run_id)

    assert store.runs().empty
    with pytest.raises(UnknownRunError):
        store.load(run_id, "summary")


@pytest.mark.parametrize("run_id", [str(uuid.uuid7()), "..", "../runs"])
def test_unknown_or_malformed_run_ids_fail(
    store: ParquetResultStore, run_id: str
) -> None:
    with pytest.raises(UnknownRunError):
        store.delete(run_id)


def test_provenance_reads_the_git_revision_and_dirty_tree(tmp_path: Path) -> None:
    git = ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "c"], check=True)
    head = subprocess.run(
        [*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()

    clean = Provenance.of_repo(tmp_path)
    (tmp_path / "new").write_text("x")
    dirty = Provenance.of_repo(tmp_path)

    assert clean == Provenance(git_sha=head, git_dirty=False)
    assert dirty.git_dirty


def test_missing_nested_values_stay_missing(
    store: ParquetResultStore, output: RunOutput
) -> None:
    positions = pd.DataFrame({"linked_order_ids": [None, ["O-1", "O-2"]]})
    sink = store.new_run(spec(), PROVENANCE)
    sink.write_reports(Reports(output.reports.fills, positions, output.reports.account))

    loaded = store.load(sink.run_id, "positions")
    assert list(loaded["linked_order_ids"]) == [None, ["O-1", "O-2"]]
