import json
import uuid
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from nautilus_run import (
    END,
    INSTRUMENT_ID,
    START,
    RunOutput,
    round_trip_with_funding,
    round_trips,
    spec,
)
from nautilus_trader.core import UUID4
from nautilus_trader.model import FundingRateUpdate, InstrumentId, PositionAdjusted

from sbt2.data.sources import Gap
from sbt2.results import (
    IncompleteRunError,
    MissingTableError,
    OutputSink,
    ParquetResultStore,
    Reports,
    RunFilter,
    RunIds,
    RunTables,
    Segment,
    UnknownRunError,
    full_metrics,
)
from sbt2.spec import ResolvedRunSpec
from strategies.ma_cross import CrossParams


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
    store: ParquetResultStore,
    output: RunOutput,
    known_gaps: tuple[Gap, ...] = (),
) -> str:
    sink = store.new_run(spec(), known_gaps)
    write(sink, output)
    sink.finalize()
    return sink.run_id


def finished(
    store: ParquetResultStore, output: RunOutput, run_spec: ResolvedRunSpec
) -> str:
    sink = store.new_run(run_spec)
    write(sink, output)
    sink.finalize()
    return sink.run_id


def other(strategy: str, part: str) -> ResolvedRunSpec:
    run_spec = spec()
    return replace(
        run_spec, strategy=replace(run_spec.strategy, strategy=strategy), part=part
    )


def listed(runs: pd.DataFrame) -> list[str]:
    return list(runs["run_id"])


@pytest.mark.unit
def test_run_ids_are_time_sortable_uuid7(store: ParquetResultStore) -> None:
    first = store.new_run(spec()).run_id
    second = store.new_run(spec()).run_id

    assert uuid.UUID(first).version == 7
    assert first < second


@pytest.mark.unit
def test_a_new_run_takes_the_run_id_it_is_given(
    store: ParquetResultStore, tmp_path: Path
) -> None:
    run_id = str(uuid.uuid7())

    sink = store.new_run(spec(), ids=RunIds(run_id))

    assert sink.run_id == run_id
    assert (tmp_path / "runs" / run_id / "spec.json").exists()


@pytest.mark.unit
def test_the_summary_holds_the_batch_id(
    store: ParquetResultStore, output: RunOutput
) -> None:
    batch_id = str(uuid.uuid7())
    sink = store.new_run(spec(), ids=RunIds(batch_id=batch_id))
    write(sink, output)
    sink.finalize()

    [summary] = store.runs().to_dict("records")
    assert summary["batch_id"] == batch_id


@pytest.mark.unit
def test_a_run_outside_a_batch_has_no_batch_id(
    store: ParquetResultStore, output: RunOutput
) -> None:
    finished_run(store, output)

    [summary] = store.runs().to_dict("records")
    assert pd.isna(summary["batch_id"])


@pytest.mark.unit
def test_the_folder_of_a_run_is_known_before_it_exists(
    store: ParquetResultStore, tmp_path: Path
) -> None:
    run_id = str(uuid.uuid7())

    assert store.folder(run_id) == tmp_path / "runs" / run_id
    assert not (tmp_path / "runs").exists()


@pytest.mark.unit
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


@pytest.mark.unit
def test_summary_holds_the_run_and_its_headline_metrics(
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
    assert summary["currency"] == "USDT"
    assert summary["trade_count"] == 2
    assert summary["total_fees"] == pytest.approx(2.0)
    assert summary["total_carry"] == pytest.approx(-5.0)
    assert summary["net_return"] == pytest.approx(993 / 10_000)
    assert summary["max_drawdown"] <= 0
    assert not {"alpha", "beta"} & set(summary)


@pytest.mark.unit
def test_the_summary_lists_the_known_gap_days_the_run_skipped(
    store: ParquetResultStore, output: RunOutput
) -> None:
    gap = Gap(INSTRUMENT_ID, FundingRateUpdate, date(2024, 1, 2))
    finished_run(store, output, known_gaps=(gap,))

    [summary] = store.runs().to_dict("records")
    assert list(summary["known_gaps"]) == [
        "BTCUSDT-LINEAR.BYBIT FundingRateUpdate 2024-01-02"
    ]


@pytest.mark.unit
def test_a_run_without_known_gaps_lists_none(
    store: ParquetResultStore, output: RunOutput
) -> None:
    finished_run(store, output)

    [summary] = store.runs().to_dict("records")
    assert list(summary["known_gaps"]) == []


@pytest.mark.unit
def test_the_summary_holds_the_split_as_json_and_the_part(
    store: ParquetResultStore, output: RunOutput
) -> None:
    finished_run(store, output)

    [summary] = store.runs().to_dict("records")
    assert summary["split"] == '{"kind":"Split","test":0.2,"validation":0.2}'
    assert summary["part"] == "train"
    assert "segment" not in summary


@pytest.mark.unit
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


@pytest.mark.unit
def test_nested_report_values_survive_the_round_trip(
    store: ParquetResultStore, output: RunOutput
) -> None:
    run_id = finished_run(store, output)

    account = store.load(run_id, "account")
    positions = store.load(run_id, "positions")
    assert list(account["info"]) == list(output.reports.account["info"])
    assert list(positions["trade_ids"]) == list(output.reports.positions["trade_ids"])


@pytest.mark.unit
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


def funding_on(instrument: str, like: PositionAdjusted) -> PositionAdjusted:
    return PositionAdjusted(
        like.trader_id,
        like.strategy_id,
        InstrumentId.from_str(instrument),
        like.position_id,
        like.account_id,
        like.adjustment_type,
        like.quantity_change,
        like.pnl_change,
        like.reason,
        UUID4(),
        like.ts_event,
        like.ts_init,
    )


@pytest.mark.unit
def test_simultaneous_funding_payments_are_stored_in_instrument_order(
    tmp_path: Path, output: RunOutput
) -> None:
    store = ParquetResultStore(tmp_path)
    sink = store.new_run(spec())
    [payment] = output.carry
    eth = funding_on("ETHUSDT-LINEAR.BYBIT", payment)
    btc = funding_on("BTCUSDT-LINEAR.BYBIT", payment)
    write(sink, RunOutput(output.snapshots, [eth, btc], output.reports))
    sink.finalize()

    carry = store.load(sink.run_id, "carry")
    assert list(carry["instrument_id"]) == [
        "BTCUSDT-LINEAR.BYBIT",
        "ETHUSDT-LINEAR.BYBIT",
    ]


@pytest.mark.unit
def test_orders_are_optional(store: ParquetResultStore, output: RunOutput) -> None:
    sink = store.new_run(spec())
    reports = output.reports
    without_orders = Reports(reports.fills, reports.positions, reports.account)
    write(sink, RunOutput(output.snapshots, output.carry, without_orders))
    sink.finalize()

    with pytest.raises(MissingTableError, match="orders"):
        store.load(sink.run_id, "orders")


@pytest.mark.unit
def test_a_run_without_funding_or_fills_finalizes(
    store: ParquetResultStore, output: RunOutput
) -> None:
    sink = store.new_run(spec())
    sink.write_equity(output.snapshots)
    sink.write_carry([])
    sink.write_reports(Reports(pd.DataFrame(), pd.DataFrame(), output.reports.account))
    sink.finalize()

    [summary] = store.runs().to_dict("records")
    assert (summary["trade_count"], summary["total_carry"]) == (0, 0.0)


@pytest.mark.unit
def test_an_unfinished_run_is_not_listed_but_keeps_its_folder(
    store: ParquetResultStore, output: RunOutput
) -> None:
    sink = store.new_run(spec())
    write(sink, output)

    assert store.runs().empty
    assert len(store.load(sink.run_id, "equity")) == len(output.snapshots)


@pytest.mark.unit
def test_empty_store_lists_no_runs_with_summary_columns(
    store: ParquetResultStore,
) -> None:
    runs = store.runs()

    assert runs.empty
    assert {"run_id", "spec_hash", "net_return"} <= set(runs.columns)


@pytest.mark.unit
def test_runs_are_listed_oldest_first(
    store: ParquetResultStore, output: RunOutput
) -> None:
    older = store.new_run(spec())
    newer = store.new_run(spec())
    for sink in (newer, older):
        write(sink, output)
        sink.finalize()

    assert listed(store.runs()) == [older.run_id, newer.run_id]


@pytest.mark.unit
def test_runs_filter_by_strategy(store: ParquetResultStore, output: RunOutput) -> None:
    finished(store, output, spec())
    run_id = finished(store, output, other("toy:Other", "train"))

    assert listed(store.runs(RunFilter(strategy="toy:Other"))) == [run_id]


@pytest.mark.unit
def test_runs_filter_by_part(store: ParquetResultStore, output: RunOutput) -> None:
    finished(store, output, spec())
    run_id = finished(store, output, other("toy:RoundTrip", "validation"))

    assert listed(store.runs(RunFilter(part="validation"))) == [run_id]


@pytest.mark.unit
def test_runs_filters_combine(store: ParquetResultStore, output: RunOutput) -> None:
    finished(store, output, spec())
    finished(store, output, other("toy:Other", "validation"))
    run_id = finished(store, output, other("toy:Other", "train"))

    assert listed(store.runs(RunFilter(strategy="toy:Other", part="train"))) == [run_id]


@pytest.mark.unit
def test_runs_filter_by_batch(store: ParquetResultStore, output: RunOutput) -> None:
    batch_id = str(uuid.uuid7())
    finished_run(store, output)
    sink = store.new_run(spec(), ids=RunIds(batch_id=batch_id))
    write(sink, output)
    sink.finalize()

    assert listed(store.runs(RunFilter(batch=batch_id))) == [sink.run_id]


@pytest.mark.unit
def test_runs_filter_by_run_ids(store: ParquetResultStore, output: RunOutput) -> None:
    first, _, third = (finished_run(store, output) for _ in range(3))

    assert listed(store.runs(RunFilter(run_ids=(third, first)))) == [first, third]


@pytest.mark.unit
def test_runs_with_no_run_ids_match_none(
    store: ParquetResultStore, output: RunOutput
) -> None:
    finished_run(store, output)

    runs = store.runs(RunFilter(run_ids=()))

    assert runs.empty
    assert {"run_id", "spec_hash", "net_return"} <= set(runs.columns)


@pytest.mark.unit
def test_listing_runs_writes_nothing_to_the_store(
    store: ParquetResultStore, output: RunOutput, tmp_path: Path
) -> None:
    finished_run(store, output)
    before = snapshot(tmp_path)

    store.runs()

    assert snapshot(tmp_path) == before


def snapshot(root: Path) -> dict[Path, int]:
    return {path: path.stat().st_mtime_ns for path in root.rglob("*")}


@pytest.mark.unit
def test_finalize_before_writing_everything_fails(
    store: ParquetResultStore, output: RunOutput
) -> None:
    sink = store.new_run(spec())
    sink.write_equity(output.snapshots)

    with pytest.raises(IncompleteRunError, match="carry, fills"):
        sink.finalize()


@pytest.mark.unit
def test_delete_removes_the_run(store: ParquetResultStore, output: RunOutput) -> None:
    run_id = finished_run(store, output)

    store.delete(run_id)

    assert store.runs().empty
    with pytest.raises(UnknownRunError):
        store.load(run_id, "summary")


@pytest.mark.unit
def test_spec_is_the_resolved_spec_document(
    store: ParquetResultStore, output: RunOutput
) -> None:
    run_id = finished_run(store, output)

    assert store.spec(run_id) == json.loads(spec().to_json())


@pytest.mark.unit
def test_an_unfinished_runs_spec_is_readable(store: ParquetResultStore) -> None:
    sink = store.new_run(spec())

    assert store.spec(sink.run_id) == json.loads(spec().to_json())


@pytest.mark.unit
def test_spec_of_an_unknown_run_fails(store: ParquetResultStore) -> None:
    with pytest.raises(UnknownRunError):
        store.spec(str(uuid.uuid7()))


@pytest.mark.unit
def test_delete_removes_an_unfinished_runs_partial_folder(
    store: ParquetResultStore, output: RunOutput, tmp_path: Path
) -> None:
    sink = store.new_run(spec())
    write(sink, output)

    store.delete(sink.run_id)

    assert not (tmp_path / "runs" / sink.run_id).exists()


@pytest.mark.unit
@pytest.mark.parametrize("run_id", [str(uuid.uuid7()), "..", "../runs"])
def test_unknown_or_malformed_run_ids_fail(
    store: ParquetResultStore, run_id: str
) -> None:
    with pytest.raises(UnknownRunError):
        store.delete(run_id)


@pytest.mark.unit
def test_missing_nested_values_stay_missing(
    store: ParquetResultStore, output: RunOutput
) -> None:
    positions = pd.DataFrame({"linked_order_ids": [None, ["O-1", "O-2"]]})
    sink = store.new_run(spec())
    sink.write_reports(Reports(output.reports.fills, positions, output.reports.account))

    loaded = store.load(sink.run_id, "positions")
    assert list(loaded["linked_order_ids"]) == [None, ["O-1", "O-2"]]


@pytest.mark.unit
def test_runs_stored_before_the_trip_column_are_still_listed(
    store: ParquetResultStore, output: RunOutput
) -> None:
    older = finished_run(store, output)
    path = store.folder(older) / "summary.parquet"
    pq.write_table(pq.read_table(path).drop_columns("drawdown_tripped_at"), path)
    newer = finished_run(store, output)

    runs = store.runs()

    assert listed(runs) == [older, newer]
    assert list(runs["drawdown_tripped_at"].isna()) == [True, True]


@pytest.mark.unit
def test_summaries_written_before_the_batch_id_still_list(
    store: ParquetResultStore, output: RunOutput
) -> None:
    run_id = finished_run(store, output)
    path = store.folder(run_id) / "summary.parquet"
    pq.write_table(pq.read_table(path).drop_columns("batch_id"), path)

    runs = store.runs()

    assert listed(runs) == [run_id]
    assert list(runs["batch_id"].isna()) == [True]


@pytest.mark.unit
def test_a_summary_written_with_alpha_and_beta_still_lists(
    store: ParquetResultStore, output: RunOutput
) -> None:
    older = finished_run(store, output)
    path = store.folder(older) / "summary.parquet"
    written = pq.read_table(path)
    for name, value in (("alpha", 0.01), ("beta", 0.9)):
        written = written.append_column(name, pa.array([value], pa.float64()))
    pq.write_table(written, path)
    newer = finished_run(store, output)

    assert listed(store.runs()) == [older, newer]


@pytest.mark.integration
def test_trade_statistics_of_a_stored_run_match_nautilus_own_analyzer(
    store: ParquetResultStore,
) -> None:
    output, own = round_trips()
    run_id = finished_run(store, output)
    stored = RunTables(
        *(store.load(run_id, table) for table in ("equity", "fills", "carry")),
        currency="USDT",
        positions=store.load(run_id, "positions"),
    )

    result = full_metrics(stored, Segment.of_run(spec()))

    expected = {
        name: value
        for name, value in own.pnls["USDT"].items()
        if name not in ("PnL (total)", "PnL% (total)")
    }
    assert len(expected) == 8
    assert {name: result.pnls[name] for name in expected} == pytest.approx(expected)
    assert result.pnls["Win Rate"] == pytest.approx(1 / 3)
    assert result.general == own.general


def importable() -> ResolvedRunSpec:
    """The toy run's spec under a strategy a stored run can be rebuilt with."""
    run_spec = spec()
    strategy = replace(
        run_spec.strategy,
        strategy="strategies.ma_cross:MovingAverageCross",
        params=asdict(CrossParams()),
    )
    return replace(run_spec, strategy=strategy)


@pytest.mark.unit
def test_a_stored_run_is_loaded_with_its_spec_tables_and_known_gaps(
    store: ParquetResultStore, output: RunOutput
) -> None:
    gap = Gap(INSTRUMENT_ID, FundingRateUpdate, date(2024, 1, 2))
    sink = store.new_run(importable(), (gap,))
    write(sink, output)
    sink.finalize()

    run = store.stored_run(sink.run_id)

    assert run.spec.hash == importable().hash
    tables, run_id = run.tables, sink.run_id
    pd.testing.assert_frame_equal(tables.equity, store.load(run_id, "equity"))
    pd.testing.assert_frame_equal(tables.fills, store.load(run_id, "fills"))
    pd.testing.assert_frame_equal(tables.carry, store.load(run_id, "carry"))
    pd.testing.assert_frame_equal(tables.positions, store.load(run_id, "positions"))
    assert tables.currency == "USDT"
    assert run.known_gaps == frozenset({gap})


@pytest.mark.unit
def test_a_failed_run_cannot_be_loaded_whole(
    store: ParquetResultStore, output: RunOutput
) -> None:
    sink = store.new_run(importable())
    write(sink, output)

    with pytest.raises(MissingTableError, match="summary"):
        store.stored_run(sink.run_id)
