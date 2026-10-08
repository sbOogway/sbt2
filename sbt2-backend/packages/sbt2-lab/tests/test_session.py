import asyncio

import pytest
from lab_kit import TOKEN, FakeServer, run, serve_job, summary

from sbt2.lab import Lab
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.results_pb2 import Metric, Metrics
from sbt2.server import Outbox

SPEC = {
    "instruments": ["BTCUSDT-PERP.BYBIT"],
    "period": ["2024-01-01", "2024-07-01"],
    "venue": "bybit",
    "capital": "10000 USDT",
    "split": {"validation": 0.2, "test": 0.2},
}


async def first_asked_answers_last(
    request: ClientMessage, _outbox: Outbox
) -> ServerMessage:
    run_id = request.get_metrics.run_id
    if run_id == "run-1":
        await asyncio.sleep(0.05)
    metric = Metric(name=f"of {run_id}", value="1")
    return ServerMessage(metrics=Metrics(last=True, entries=[metric]))


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_concurrent_requests_get_their_own_replies() -> None:
    server = FakeServer()
    serve_job(server, [summary("run-1"), summary("run-2")])
    server.answer("get_metrics", first_asked_answers_last)
    names: list[str] = []

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            first, second = await lab.run(SPEC, "my_strats:Cross")
            metrics = await asyncio.gather(first.metrics(), second.metrics())
            names.extend(each.iloc[0]["name"] for each in metrics)

    run(scenario, server)

    assert names == ["of run-1", "of run-2"]
