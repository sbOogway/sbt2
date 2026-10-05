import json
from collections.abc import Iterator, Mapping
from dataclasses import fields
from typing import Any

import pandas as pd

from sbt2.core import results as core
from sbt2.protocol.v1 import results_pb2 as wire
from sbt2.protocol.v1.envelope_pb2 import ServerMessage
from sbt2.server.results.encoding import headline
from sbt2.server.results.streaming import checked, records

_HEADLINE = {each.name for each in fields(core.HeadlineMetrics)}
_HEADER = ("name", "strategy", "context_json", "source")


def study_summaries(store: core.ResultStore) -> Iterator[wire.StudySummary]:
    for row in core.study_list(store).to_dict("records"):
        yield wire.StudySummary(
            name=row["study"], strategy=row["strategy"], run_count=row["runs"]
        )


def study_chunks(
    store: core.ResultStore, request_id: int, name: str
) -> Iterator[ServerMessage]:
    """A study as chunks of its runs; the first one alone carries the study's
    name, strategy, context and source."""
    study = store.study(name)
    detail = wire.StudyDetail(
        name=study.name,
        strategy=study.strategy,
        context_json=json.dumps(study.context),
        source=study.source,
    )
    first = checked(ServerMessage(request_id=request_id, study_detail=detail))
    for chunk in records(first, "runs", _runs(store, name)):
        if chunk.study_detail.index > 0:
            for field in _HEADER:
                chunk.study_detail.ClearField(field)
        yield chunk


def _runs(store: core.ResultStore, name: str) -> Iterator[wire.StudyRun]:
    table = core.study_table(store, name)
    for run_id, row in zip(table.index, table.to_dict("records"), strict=True):
        yield wire.StudyRun(
            run_id=run_id,
            part=row["part"],
            varying_params_json=json.dumps(_varying(row), default=str),
            headline=headline(row),
        )


def _varying(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key != "part" and key not in _HEADLINE and not _missing(value)
    }


def _missing(value: Any) -> bool:
    return not isinstance(value, list | tuple) and bool(pd.isna(value))
