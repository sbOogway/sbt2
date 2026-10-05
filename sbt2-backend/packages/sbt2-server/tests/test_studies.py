from pathlib import Path

import pytest
from results_kit import ask, stored_studies

from sbt2.core import results as core
from sbt2.core.config import Root
from sbt2.protocol.v1.envelope_pb2 import ClientMessage
from sbt2.protocol.v1.results_pb2 import ListStudies
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
