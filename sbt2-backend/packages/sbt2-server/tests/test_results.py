import uuid
from pathlib import Path
from unittest.mock import create_autospec

import pandas as pd
import pytest
from results_kit import ask, stored, summary_record

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.protocol.v1.envelope_pb2 import ClientMessage
from sbt2.protocol.v1.results_pb2 import (
    BenchmarkKind,
    BenchmarkSelection,
    GetRun,
    GetSeries,
    GetTearsheet,
    ListRuns,
    RunFilter,
    RunIds,
)
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server.results import routes


@pytest.mark.unit
def test_run_filters_preserve_presence_and_empty_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = create_autospec(core.ResultStore, instance=True)
    store.runs.return_value = pd.DataFrame()
    monkeypatch.setattr(core, "store_at", lambda _root: store)
    cases = [
        (RunFilter(), core.RunFilter()),
        (RunFilter(run_ids=RunIds()), core.RunFilter(run_ids=())),
        (RunFilter(strategy="", part="test"), core.RunFilter(strategy="", part="test")),
        (
            RunFilter(
                strategy="s",
                part="train",
                batch="b",
                study="x",
                run_ids=RunIds(values=["id"]),
            ),
            core.RunFilter(
                strategy="s", part="train", batch="b", study="x", run_ids=("id",)
            ),
        ),
    ]
    for selected, expected in cases:
        [reply] = ask(
            routes(Root(Path("unused"))),
            ClientMessage(request_id=1, list_runs=ListRuns(filter=selected)),
        )
        store.runs.assert_called_with(expected)
        assert reply.run_list.last
        assert list(reply.run_list.runs) == []


@pytest.mark.integration
def test_lists_and_summaries_match_the_stored_runs(tmp_path: Path) -> None:
    run = stored(tmp_path)
    run.store.new_run(run.store.stored_run(run.run_id).spec)
    handlers = routes(run.root)
    [listed] = ask(handlers, ClientMessage(request_id=10, list_runs=ListRuns()))
    [summary] = ask(
        handlers, ClientMessage(request_id=11, get_run=GetRun(run_id=run.run_id))
    )
    assert [each.run_id for each in listed.run_list.runs] == [run.run_id]
    assert listed.run_list.last
    assert listed.run_list.runs[0] == summary.run_summary
    assert summary.request_id == 11
    assert summary.run_summary.headline.trade_count == 2
    assert float(summary.run_summary.headline.total_carry) == -5
    assert summary.run_summary.batch_id == "batch-1"


@pytest.mark.unit
def test_summary_encoding_preserves_missing_values_and_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = create_autospec(core.ResultStore, instance=True)
    store.load.return_value = pd.DataFrame([summary_record()])
    monkeypatch.setattr(core, "store_at", lambda _root: store)
    [reply] = ask(
        routes(Root(Path("unused"))),
        ClientMessage(request_id=1, get_run=GetRun(run_id=summary_record()["run_id"])),
    )
    summary = reply.run_summary
    assert summary.start_at.seconds == 1704067200
    assert summary.start_at.nanos == 123456789
    assert not summary.HasField("drawdown_tripped_at")
    assert not summary.HasField("batch_id")
    assert not summary.headline.HasField("sharpe")
    assert not summary.headline.HasField("annualized_return")
    assert summary.headline.HasField("net_return")
    assert float(summary.headline.net_return) == 0
    assert float(summary.headline.total_fees) == 0.000001


@pytest.mark.integration
def test_result_errors_use_protocol_codes(tmp_path: Path) -> None:
    run = stored(tmp_path)
    handlers = routes(run.root)
    for run_id in ("../escape", "not-a-uuid", str(uuid.uuid7())):
        [reply] = ask(
            handlers, ClientMessage(request_id=1, get_run=GetRun(run_id=run_id))
        )
        assert reply.error.code == ErrorCode.ERROR_CODE_NOT_FOUND
        assert str(tmp_path) not in reply.error.message
    selections = [
        BenchmarkSelection(kind=BenchmarkKind.BENCHMARK_KIND_NONE, instrument_id="X"),
        BenchmarkSelection(
            kind=BenchmarkKind.BENCHMARK_KIND_BUY_AND_HOLD, instrument_id="not-one"
        ),
        BenchmarkSelection(kind=BenchmarkKind.ValueType(99)),
    ]
    for selection in selections:
        tearsheet = GetTearsheet(run_id=run.run_id, benchmark=selection)
        [reply] = ask(handlers, ClientMessage(request_id=4, get_tearsheet=tearsheet))
        assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT
    (run.store.folder(run.run_id) / "summary.parquet").unlink()
    [reply] = ask(
        handlers, ClientMessage(request_id=2, get_run=GetRun(run_id=run.run_id))
    )
    assert reply.error.code == ErrorCode.ERROR_CODE_NOT_FOUND
    [reply] = ask(
        handlers,
        ClientMessage(request_id=3, get_series=GetSeries(run_id=str(uuid.uuid7()))),
    )
    assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT


@pytest.mark.unit
def test_chunks_reassemble_within_the_envelope_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = summary_record()
    record["params"] = '{"text":"' + "x" * 300_000 + '"}'
    records = [{**record, "run_id": str(uuid.uuid7())} for _ in range(9)]
    store = create_autospec(core.ResultStore, instance=True)
    store.runs.return_value = pd.DataFrame(records)
    monkeypatch.setattr(core, "store_at", lambda _root: store)
    replies = ask(
        routes(Root(Path("unused"))),
        ClientMessage(request_id=2**64 - 1, list_runs=ListRuns()),
    )
    assert len(replies) > 1
    assert all(reply.ByteSize() <= 1_048_576 for reply in replies)
    assert {reply.request_id for reply in replies} == {2**64 - 1}
    assert [reply.run_list.index for reply in replies] == list(range(len(replies)))
    assert [reply.run_list.last for reply in replies] == [False] * (
        len(replies) - 1
    ) + [True]
    assert [run.run_id for reply in replies for run in reply.run_list.runs] == [
        row["run_id"] for row in records
    ]


@pytest.mark.unit
@pytest.mark.parametrize("body", ["list_runs", "get_run"])
def test_an_oversized_record_returns_resource_exhausted(
    body: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = {**summary_record(), "params": "x" * 1_048_576}
    store = create_autospec(core.ResultStore, instance=True)
    store.runs.return_value = store.load.return_value = pd.DataFrame([record])
    monkeypatch.setattr(core, "store_at", lambda _root: store)
    request = ClientMessage(request_id=1)
    getattr(request, body).SetInParent()
    if body == "get_run":
        request.get_run.run_id = record["run_id"]
    [reply] = ask(routes(Root(Path("unused"))), request)
    assert reply.error.code == ErrorCode.ERROR_CODE_RESOURCE_EXHAUSTED
    assert reply.ByteSize() <= 1_048_576
