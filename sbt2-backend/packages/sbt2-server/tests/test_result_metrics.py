from pathlib import Path

import pytest
from results_kit import ask, stored

from sbt2.core import results as core
from sbt2.protocol.v1.envelope_pb2 import ClientMessage
from sbt2.protocol.v1.results_pb2 import GetMetrics, MetricGroup
from sbt2.server.results import routes


@pytest.mark.integration
def test_full_metrics_match_core(tmp_path: Path) -> None:
    run = stored(tmp_path)
    loaded = run.store.stored_run(run.run_id)
    expected = core.full_metrics(loaded.tables, core.Segment.of_run(loaded.spec))
    replies = ask(
        routes(run.root),
        ClientMessage(request_id=12, get_metrics=GetMetrics(run_id=run.run_id)),
    )
    assert replies[-1].metrics.last
    assert {reply.metrics.currency for reply in replies} == {"USDT"}
    values = {
        (entry.group, entry.instrument_id, entry.name): float(entry.value)
        if entry.HasField("value")
        else None
        for reply in replies
        for entry in reply.metrics.entries
    }
    groups = [
        (MetricGroup.METRIC_GROUP_PNLS, "", expected.pnls),
        (MetricGroup.METRIC_GROUP_RETURNS, "", expected.returns),
        (MetricGroup.METRIC_GROUP_GENERAL, "", expected.general),
    ]
    groups.extend(
        (MetricGroup.METRIC_GROUP_INSTRUMENT_PNLS, instrument, statistics)
        for instrument, statistics in expected.pnls_by_instrument.items()
    )
    wanted = {
        (group, instrument, name): value
        for group, instrument, statistics in groups
        for name, value in statistics.items()
    }
    wanted[
        (
            MetricGroup.METRIC_GROUP_PROBABILISTIC_SHARPE,
            "",
            "Probabilistic Sharpe Ratio",
        )
    ] = expected.probabilistic_sharpe
    assert values == wanted


@pytest.mark.integration
def test_metric_chunks_preserve_groups_and_missing_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = stored(tmp_path)
    statistics = {
        str(index) + "x" * 300_000: float(index) if index else None
        for index in range(8)
    }
    metrics = core.FullMetrics({}, statistics, {}, {}, None)
    monkeypatch.setattr(core, "full_metrics", lambda _tables, _segment: metrics)
    replies = ask(
        routes(run.root),
        ClientMessage(request_id=2**64 - 1, get_metrics=GetMetrics(run_id=run.run_id)),
    )
    assert len(replies) > 1
    assert all(reply.ByteSize() <= 1_048_576 for reply in replies)
    assert all(reply.request_id == 2**64 - 1 for reply in replies)
    assert [reply.metrics.index for reply in replies] == list(range(len(replies)))
    assert sum(reply.metrics.last for reply in replies) == 1
    assert replies[-1].metrics.last
    entries = [entry for reply in replies for entry in reply.metrics.entries]
    assert len(entries) == 9
    assert not entries[0].HasField("value")
    assert not entries[-1].HasField("value")
