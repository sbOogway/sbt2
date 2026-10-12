import logging

import pandas as pd
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


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_progress_shows_the_finished_runs(capsys: pytest.CaptureFixture[str]) -> None:
    server = FakeServer()
    running = JobUpdate(
        runs=[RunState(run_id="run-1", state=RunStatus.RUN_STATUS_RUNNING)]
    )
    serve_job(
        server,
        [summary("run-1"), summary("run-2")],
        [running, finished("run-1", "run-2")],
    )

    ran(server)

    assert "2/2" in capsys.readouterr().err


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_job_log_lines_go_to_the_lab_logger(caplog: pytest.LogCaptureFixture) -> None:
    server = FakeServer()
    printed = JobUpdate(log_lines=["run-1 started", "run-1 at 2024-02-01"])
    serve_job(server, [summary("run-1")], [printed, finished("run-1")])

    with caplog.at_level(logging.INFO, logger="sbt2.lab"):
        ran(server)

    assert [each.getMessage() for each in caplog.records] == [
        "run-1 started",
        "run-1 at 2024-02-01",
    ]


@pytest.mark.integration
@pytest.mark.usefixtures("strategies")
def test_runs_show_their_headline_metrics_as_a_table() -> None:
    server = FakeServer()
    serve_job(server, [summary("run-1"), summary("run-2", sharpe="0.7")])

    runs = ran(server)

    table = runs.table()
    assert list(table.index) == ["run-1", "run-2"]
    assert table.loc["run-2", "sharpe"] == 0.7
    assert table.loc["run-1", "part"] == "train"
    assert table.loc["run-1", "fast"] == 10
    assert pd.isna(table.loc["run-1", "net_return"])
    assert "run-2" in runs._repr_html_()
