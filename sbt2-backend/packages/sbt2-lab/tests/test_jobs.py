import pytest
from lab_kit import TOKEN, FakeServer, finished, replying, run, serve_job, summary

from sbt2.lab import JobFailedError, Lab, Runs, ServerError
from sbt2.protocol.v1.envelope_pb2 import ServerMessage
from sbt2.protocol.v1.runs_pb2 import JobState, JobUpdate, RunState, RunStatus
from sbt2.protocol.v1.types_pb2 import Error, ErrorCode

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


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_a_failed_job_raises_with_the_reason_of_its_failed_run() -> None:
    server = FakeServer()
    failed = JobUpdate(
        state=JobState.JOB_STATE_FAILED,
        runs=[
            RunState(run_id="run-1", state=RunStatus.RUN_STATUS_FINISHED),
            RunState(
                run_id="run-2", state=RunStatus.RUN_STATUS_FAILED, reason="no data"
            ),
        ],
    )
    serve_job(server, [summary("run-1"), summary("run-2")], [failed])

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            with pytest.raises(JobFailedError, match="run-2: no data"):
                await lab.run(SPEC, STRATEGY)

    run(scenario, server)

    assert server.received("list_runs") == []


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_a_server_error_raises_with_its_code_and_message() -> None:
    server = FakeServer()
    error = Error(code=ErrorCode.ERROR_CODE_INVALID_ARGUMENT, message="bad venue")
    server.answer("submit_run", replying(ServerMessage(error=error)))

    async def scenario(url: str) -> None:
        async with await Lab.connect(url, TOKEN) as lab:
            with pytest.raises(ServerError) as raised:
                await lab.run(SPEC, STRATEGY)
            assert (raised.value.code, raised.value.message) == (
                "ERROR_CODE_INVALID_ARGUMENT",
                "bad venue",
            )

    run(scenario, server)
