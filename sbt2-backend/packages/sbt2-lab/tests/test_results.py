import math
from collections.abc import Awaitable, Callable

import pandas as pd
import pytest
from lab_kit import TOKEN, FakeServer, run, serve_job, summary

from sbt2.lab import Lab, Run
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.results_pb2 import Metric, MetricGroup, Metrics
from sbt2.server import Handler, Outbox

SPEC = {
    "instruments": ["BTCUSDT-PERP.BYBIT"],
    "period": ["2024-01-01", "2024-07-01"],
    "venue": "bybit",
    "capital": "10000 USDT",
    "split": {"validation": 0.2, "test": 0.2},
}


def chunked(*chunks: ServerMessage) -> Handler:
    """Sends every chunk but the last before it replies with the last."""

    async def reply(request: ClientMessage, outbox: Outbox) -> ServerMessage:
        for chunk in chunks[:-1]:
            chunk.request_id = request.request_id
            await outbox.send(chunk)
        return chunks[-1]

    return reply


def fetched[T](server: FakeServer, fetch: Callable[[Run], Awaitable[T]]) -> T:
    serve_job(server, [summary("run-1")])
    results: list[T] = []

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            [ran] = await lab.run(SPEC, "my_strats:Cross")
            results.append(await fetch(ran))

    run(scenario, server)
    return results[0]


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_metrics_come_as_a_table_with_absent_values_as_nan() -> None:
    server = FakeServer()
    sharpe = Metric(group=MetricGroup.METRIC_GROUP_RETURNS, name="Sharpe", value="1.5")
    pnl = Metric(
        group=MetricGroup.METRIC_GROUP_INSTRUMENT_PNLS,
        name="PnL",
        instrument_id="BTCUSDT-PERP.BYBIT",
    )
    server.answer(
        "get_metrics",
        chunked(
            ServerMessage(metrics=Metrics(index=0, currency="USDT", entries=[sharpe])),
            ServerMessage(metrics=Metrics(index=1, last=True, entries=[pnl])),
        ),
    )

    metrics = fetched(server, Run.metrics)

    assert list(metrics.columns) == ["group", "name", "instrument_id", "value"]
    assert metrics.iloc[0][["group", "name", "value"]].to_list() == [
        "returns",
        "Sharpe",
        1.5,
    ]
    assert pd.isna(metrics.iloc[0]["instrument_id"])
    assert metrics.iloc[1]["group"] == "instrument_pnls"
    assert metrics.iloc[1]["instrument_id"] == "BTCUSDT-PERP.BYBIT"
    assert math.isnan(metrics.iloc[1]["value"])
    [asked] = server.received("get_metrics")
    assert asked.get_metrics.run_id == "run-1"
