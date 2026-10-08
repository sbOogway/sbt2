import pytest
from lab_kit import TOKEN, FakeServer, finished, run, serve_job, summary

from sbt2.lab import Lab, Runs
from sbt2.protocol.v1.runs_pb2 import JobUpdate, RunState, RunStatus

SPEC = {
    "instruments": ["BTCUSDT-PERP.BYBIT"],
    "period": ["2024-01-01", "2024-07-01"],
    "venue": "bybit",
    "capital": "10000 USDT",
    "split": {"validation": 0.2, "test": 0.2},
}
STRATEGY = "my_strats:Cross"


def ran(server: FakeServer) -> Runs:
    runs: list[Runs] = []

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            runs.append(await lab.run(SPEC, STRATEGY))

    run(scenario, server)
    return runs[0]


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_run_returns_the_runs_once_the_job_is_finished() -> None:
    server = FakeServer()
    running = JobUpdate(
        runs=[RunState(run_id="run-1", state=RunStatus.RUN_STATUS_RUNNING)]
    )
    serve_job(
        server,
        [summary("run-1"), summary("run-2", sharpe="0.7")],
        [running, finished("run-1", "run-2")],
    )

    runs = ran(server)

    assert [each.run_id for each in runs] == ["run-1", "run-2"]
    assert runs[1].headline["sharpe"] == "0.7"
    assert runs[0].params == {"fast": 10}
    [listed] = server.received("list_runs")
    assert list(listed.list_runs.filter.run_ids.values) == ["run-1", "run-2"]


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_a_job_over_before_the_subscription_returns_at_once() -> None:
    server = FakeServer()
    serve_job(server, [summary("run-1")])

    runs = ran(server)

    assert [each.run_id for each in runs] == ["run-1"]
