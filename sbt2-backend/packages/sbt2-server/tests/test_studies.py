import json
import uuid
from pathlib import Path
from unittest.mock import create_autospec

import pandas as pd
import pytest
from results_kit import ask, stored_studies

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.protocol.v1.envelope_pb2 import ClientMessage
from sbt2.protocol.v1.results_pb2 import GetStudy, ListStudies
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server.limits import MAX_ENVELOPE
from sbt2.server.results import routes

STUDIES = {
    "sweep": [{"hold_bars": 2}, {"hold_bars": 3}],
    "single": [{"hold_bars": 2}],
}


@pytest.mark.integration
def test_list_studies_names_each_study_with_its_strategy_and_run_count(
    tmp_path: Path,
) -> None:
    run = stored_studies(tmp_path, STUDIES)

    [reply] = ask(
        routes(run.root), ClientMessage(request_id=4, list_studies=ListStudies())
    )

    expected = core.study_list(run.store)
    assert reply.request_id == 4
    assert reply.study_list.index == 0
    assert reply.study_list.last
    assert [
        (each.name, each.strategy, each.run_count) for each in reply.study_list.studies
    ] == list(expected.itertuples(index=False, name=None))
    assert {each.name: each.run_count for each in reply.study_list.studies} == {
        "sweep": 2,
        "single": 1,
    }


@pytest.mark.integration
def test_list_studies_without_studies_is_one_empty_last_chunk(tmp_path: Path) -> None:
    replies = ask(
        routes(Root(tmp_path)), ClientMessage(request_id=1, list_studies=ListStudies())
    )

    [reply] = replies
    assert reply.study_list.index == 0
    assert reply.study_list.last
    assert list(reply.study_list.studies) == []


@pytest.mark.integration
def test_get_study_sends_its_context_source_and_comparison_rows(
    tmp_path: Path,
) -> None:
    run = stored_studies(tmp_path, STUDIES)

    [reply] = ask(
        routes(run.root),
        ClientMessage(request_id=5, get_study=GetStudy(name="sweep")),
    )

    study = run.store.study("sweep")
    table = core.study_table(run.store, "sweep")
    detail = reply.study_detail
    assert reply.request_id == 5
    assert (detail.index, detail.last) == (0, True)
    assert (detail.name, detail.strategy) == ("sweep", study.strategy)
    assert json.loads(detail.context_json) == study.context
    assert detail.source == study.source
    assert [each.run_id for each in detail.runs] == list(table.index)
    assert [each.part for each in detail.runs] == list(table["part"])
    assert [float(each.headline.net_return) for each in detail.runs] == pytest.approx(
        list(table["net_return"])
    )
    assert [each.headline.trade_count for each in detail.runs] == list(
        table["trade_count"]
    )


@pytest.mark.integration
def test_get_study_rows_hold_only_the_varying_params(tmp_path: Path) -> None:
    fixed = {"mode": "trade"}
    run = stored_studies(
        tmp_path, {"sweep": [{**fixed, "hold_bars": 2}, {**fixed, "hold_bars": 3}]}
    )

    [reply] = ask(
        routes(run.root),
        ClientMessage(request_id=1, get_study=GetStudy(name="sweep")),
    )

    varying = [json.loads(each.varying_params_json) for each in reply.study_detail.runs]
    assert varying == [{"hold_bars": 2}, {"hold_bars": 3}]


@pytest.mark.integration
def test_an_unknown_study_is_not_found(tmp_path: Path) -> None:
    run = stored_studies(tmp_path, STUDIES)

    [reply] = ask(
        routes(run.root),
        ClientMessage(request_id=1, get_study=GetStudy(name="nowhere")),
    )

    assert reply.WhichOneof("body") == "error"
    assert reply.error.code == ErrorCode.ERROR_CODE_NOT_FOUND


@pytest.mark.unit
def test_get_study_chunks_reassemble_within_the_envelope_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ids = [str(uuid.uuid7()) for _ in range(9)]
    store = create_autospec(core.ResultStore, instance=True)
    store.study.return_value = core.StoredStudy(
        "big", {"strategy": "example:Trend"}, "# source\n"
    )
    monkeypatch.setattr(core, "store_at", lambda _root: store)
    table = pd.DataFrame(
        {
            "part": "train",
            "text": "x" * 300_000,
            "net_return": 0.1,
            "annualized_return": 0.1,
            "sharpe": 1.0,
            "max_drawdown": -0.1,
            "trade_count": 2,
            "total_fees": 1.0,
            "total_carry": 0.0,
        },
        index=pd.Index(ids, name="run_id"),
    )
    monkeypatch.setattr(core, "study_table", lambda _store, _name: table)

    replies = ask(
        routes(Root(Path("unused"))),
        ClientMessage(request_id=2**64 - 1, get_study=GetStudy(name="big")),
    )

    details = [each.study_detail for each in replies]
    assert len(replies) > 1
    assert all(each.ByteSize() <= MAX_ENVELOPE for each in replies)
    assert [each.index for each in details] == list(range(len(replies)))
    assert [each.last for each in details] == [False] * (len(replies) - 1) + [True]
    assert (details[0].name, details[0].source) == ("big", "# source\n")
    for later in details[1:]:
        header = (later.name, later.strategy, later.context_json, later.source)
        assert header == ("", "", "", "")
    assert [run.run_id for each in details for run in each.runs] == ids


@pytest.mark.unit
def test_a_study_whose_header_alone_is_too_large_is_resource_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = create_autospec(core.ResultStore, instance=True)
    store.study.return_value = core.StoredStudy(
        "big", {"strategy": "example:Trend"}, "x" * MAX_ENVELOPE
    )
    monkeypatch.setattr(core, "store_at", lambda _root: store)
    monkeypatch.setattr(core, "study_table", lambda _store, _name: pd.DataFrame())

    [reply] = ask(
        routes(Root(Path("unused"))),
        ClientMessage(request_id=1, get_study=GetStudy(name="big")),
    )

    assert reply.error.code == ErrorCode.ERROR_CODE_RESOURCE_EXHAUSTED
