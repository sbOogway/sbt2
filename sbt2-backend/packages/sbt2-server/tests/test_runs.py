import asyncio
import builtins
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import override

import pytest
from runs_kit import (
    MODULE,
    STRATEGY,
    FakeWorker,
    FakeWorkers,
    ScriptedSubscription,
    Session,
    deployed,
    finished,
    run_table,
    submit_run,
    until,
)

from sbt2.core.config import Root
from sbt2.core.results import ParquetResultStore
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.results_pb2 import GetRun
from sbt2.protocol.v1.runs_pb2 import (
    CancelJob,
    Job,
    JobState,
    JobSubmitted,
    JobUpdate,
    ListJobs,
    RunStatus,
    SubscribeJob,
    Unsubscribe,
)
from sbt2.protocol.v1.types_pb2 import ErrorCode
from sbt2.server import results
from sbt2.server import runs as area
from sbt2.server.limits import MAX_ENVELOPE
from sbt2.server.runs.jobs import Jobs, Submission, Subscription
from sbt2.server.runs.lines import LINE_LIMIT, Lines
from sbt2.server.runs.memory import InMemoryJobs
from sbt2.server.runs.pushes import update_messages
from sbt2.server.runs.wire import (
    Done,
    Exited,
    Failed,
    Finished,
    LogLines,
    Planned,
    Started,
)

type Scenario = Callable[[Session, Jobs], Awaitable[None]]

RUN_IDS = ("run-1", "run-2")


def in_one_loop(scenario: Awaitable[None]) -> None:
    async def bounded() -> None:
        await asyncio.wait_for(scenario, 240)

    asyncio.run(bounded())


def real_jobs(path: Path) -> tuple[Root, Jobs]:
    root, config = deployed(path)
    return root, area.local_jobs(root, config)


def planning(worker: FakeWorker) -> None:
    worker.emit(Planned(RUN_IDS))


def submitted_job(reply: ServerMessage) -> str:
    assert reply.WhichOneof("body") == "job_submitted", reply
    return reply.job_submitted.job_id


async def subscribe(session: Session, job_id: str) -> ServerMessage:
    reply = await session.ask(ClientMessage(subscribe_job=SubscribeJob(job_id=job_id)))
    assert reply.WhichOneof("body") == "job_subscribed", reply
    return reply


def updates(session: Session) -> list[JobUpdate]:
    return [each.job_update for each in session.pushes]


def final_update(session: Session) -> JobUpdate | None:
    return next(
        (
            each
            for each in updates(session)
            if each.state == JobState.JOB_STATE_FINISHED
        ),
        None,
    )


def states(job: Job) -> list[RunStatus.ValueType]:
    return [each.state for each in job.runs]


def alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except FileNotFoundError:
        return False
    return stat.rpartition(")")[2].split()[0] != "Z"


@pytest.mark.integration
def test_submit_run_answers_job_submitted_with_its_run_ids(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, jobs = real_jobs(tmp_path)
        session = Session(area.routes(jobs))
        table = run_table(params={"hold_bars": [2, 3]})

        reply = await session.ask(submit_run(table))

        job_id = submitted_job(reply)
        assert len(reply.job_submitted.run_ids) == 2
        job = await finished(jobs, job_id)
        assert job.state == JobState.JOB_STATE_FINISHED
        assert [each.run_id for each in job.runs] == list(reply.job_submitted.run_ids)

    in_one_loop(scenario())


@pytest.mark.integration
def test_a_finished_job_stores_each_run_with_its_strategy_py(tmp_path: Path) -> None:
    async def scenario() -> None:
        root, jobs = real_jobs(tmp_path)
        session = Session({**area.routes(jobs), **results.routes(root)})
        reply = await session.ask(submit_run(run_table(params={"hold_bars": [2, 3]})))
        await finished(jobs, submitted_job(reply))

        store = ParquetResultStore(root.results)

        assert sorted(store.runs()["run_id"]) == sorted(reply.job_submitted.run_ids)
        for run_id in reply.job_submitted.run_ids:
            assert (store.folder(run_id) / "strategy.py").read_text() == STRATEGY
            summary = await session.ask(ClientMessage(get_run=GetRun(run_id=run_id)))
            assert summary.run_summary.run_id == run_id

    in_one_loop(scenario())


@pytest.mark.integration
def test_an_invalid_spec_answers_invalid_argument_and_starts_no_job(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        _, jobs = real_jobs(tmp_path)
        session = Session(area.routes(jobs))
        table = run_table()
        del table["split"]

        reply = await session.ask(submit_run(table))
        listed = await session.ask(ClientMessage(list_jobs=ListJobs()))

        assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT
        assert "needs a split" in reply.error.message
        assert list(listed.jobs.jobs) == []

    in_one_loop(scenario())


@pytest.mark.integration
def test_an_unknown_venue_profile_answers_not_found(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, jobs = real_jobs(tmp_path)
        session = Session(area.routes(jobs))

        reply = await session.ask(submit_run(run_table(venue="nowhere")))

        assert reply.error.code == ErrorCode.ERROR_CODE_NOT_FOUND
        assert "nowhere" in reply.error.message

    in_one_loop(scenario())


@pytest.mark.unit
@pytest.mark.parametrize(
    "name", ["json", "os", "sbt2", "not-an-identifier", "1st", "class", ""]
)
def test_a_strategy_module_named_like_an_installed_module_is_invalid_argument(
    name: str,
) -> None:
    async def scenario() -> None:
        workers = FakeWorkers(planning)
        session = Session(area.routes(InMemoryJobs(workers)))
        table = run_table(strategy=f"{name}:Uploaded")

        reply = await session.ask(submit_run(table))

        assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT
        assert workers.launched == []

    in_one_loop(scenario())


@pytest.mark.unit
def test_a_spec_must_name_a_class_of_the_uploaded_module() -> None:
    async def scenario() -> None:
        workers = FakeWorkers(planning)
        session = Session(area.routes(InMemoryJobs(workers)))
        request = submit_run(run_table())
        request.submit_run.spec.strategy = "elsewhere:Uploaded"

        reply = await session.ask(request)

        assert reply.error.code == ErrorCode.ERROR_CODE_INVALID_ARGUMENT
        assert workers.launched == []

    in_one_loop(scenario())


@pytest.mark.integration
def test_the_server_process_never_imports_the_uploaded_module(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, jobs = real_jobs(tmp_path)
        session = Session(area.routes(jobs))

        await finished(jobs, submitted_job(await session.ask(submit_run(run_table()))))

        assert MODULE not in sys.modules
        assert not hasattr(builtins, "UPLOADED_MODULE_WAS_IMPORTED")

    in_one_loop(scenario())


@pytest.mark.integration
def test_the_job_process_runs_without_the_server_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SBT2_SERVER_TOKEN", "s3cret")
    monkeypatch.setenv("SBT2_SERVER_HOST", "0.0.0.0")
    monkeypatch.setenv("SBT2_PROBE", "kept")
    seen = tmp_path / "environment.json"

    async def scenario() -> None:
        _, jobs = real_jobs(tmp_path)
        session = Session(area.routes(jobs))
        table = run_table(params={"mode": "environment", "out": str(seen)})

        await finished(jobs, submitted_job(await session.ask(submit_run(table))))

    in_one_loop(scenario())

    names = json.loads(seen.read_text())
    assert "SBT2_PROBE" in names
    assert [each for each in names if each.startswith("SBT2_SERVER_")] == []


@pytest.mark.integration
def test_subscribe_job_first_sends_the_current_state_then_updates_until_terminal(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        _, jobs = real_jobs(tmp_path)
        session = Session(area.routes(jobs))
        table = run_table(params={"hold_bars": [2, 3]})
        job_id = submitted_job(await session.ask(submit_run(table)))

        subscribed = await subscribe(session, job_id)
        final = await until(lambda: final_update(session))

        snapshot = subscribed.job_subscribed
        assert snapshot.subscription_id > 0
        assert snapshot.job.job_id == job_id
        assert snapshot.job.state in (
            JobState.JOB_STATE_QUEUED,
            JobState.JOB_STATE_RUNNING,
        )
        assert final.state == JobState.JOB_STATE_FINISHED
        for push in session.pushes:
            assert push.request_id == 0
            assert push.subscription_id == snapshot.subscription_id
        last = {each.run_id: each.state for u in updates(session) for each in u.runs}
        assert set(last.values()) == {RunStatus.RUN_STATUS_FINISHED}
        assert len(last) == 2

    in_one_loop(scenario())


@pytest.mark.integration
def test_subscribing_after_reconnect_gets_the_current_state_first(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        _, jobs = real_jobs(tmp_path)
        routes = area.routes(jobs)
        job_id = submitted_job(await Session(routes).ask(submit_run(run_table())))
        await finished(jobs, job_id)

        again = Session(routes)
        subscribed = await subscribe(again, job_id)
        await until(lambda: updates(again) or None)

        assert subscribed.job_subscribed.job.state == JobState.JOB_STATE_FINISHED
        assert states(subscribed.job_subscribed.job) == [RunStatus.RUN_STATUS_FINISHED]
        [only] = updates(again)
        assert only.state == JobState.JOB_STATE_FINISHED

    in_one_loop(scenario())


class Static(Jobs):
    def __init__(self, subscription: Subscription) -> None:
        self._subscription = subscription

    @override
    async def submit(self, submission: Submission) -> JobSubmitted:
        raise NotImplementedError

    @override
    async def cancel(self, job_id: str) -> None:
        raise NotImplementedError

    @override
    def list_jobs(self) -> list[Job]:
        return []

    @override
    def subscribe(self, job_id: str) -> Subscription:
        return self._subscription


@pytest.mark.unit
def test_job_updates_are_coalesced_to_a_few_per_second() -> None:
    lines = [f"line {number}" for number in range(300)]
    emitted = [
        JobUpdate(log_lines=[line], state=JobState.JOB_STATE_RUNNING) for line in lines
    ]
    emitted[-1].state = JobState.JOB_STATE_FINISHED
    subscription = ScriptedSubscription(emitted)

    async def scenario() -> None:
        session = Session(area.routes(Static(subscription)))
        await subscribe(session, "job")
        await until(lambda: True if subscription.closed else None, timeout=10)
        pushed = updates(session)
        assert len(pushed) <= 2
        assert [line for each in pushed for line in each.log_lines] == lines
        assert pushed[-1].state == JobState.JOB_STATE_FINISHED

    in_one_loop(scenario())


@pytest.mark.unit
def test_log_lines_of_the_job_arrive_in_batches() -> None:
    async def scenario() -> None:
        workers = FakeWorkers(planning)
        jobs = InMemoryJobs(workers)
        session = Session(area.routes(jobs))
        job_id = submitted_job(await session.ask(submit_run(run_table())))
        [(_, worker)] = workers.launched
        await subscribe(session, job_id)

        worker.emit(LogLines(("one", "two", "three")))
        pushed = await until(lambda: updates(session) or None)
        worker.emit(Done(), Exited(0))
        await finished(jobs, job_id)

        assert [line for each in pushed for line in each.log_lines] == [
            "one",
            "two",
            "three",
        ]

    in_one_loop(scenario())


@pytest.mark.integration
def test_the_logs_of_a_real_job_reach_its_subscriber(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, jobs = real_jobs(tmp_path)
        session = Session(area.routes(jobs))
        table = run_table(params={"mode": "print"})
        job_id = submitted_job(await session.ask(submit_run(table)))
        subscribed = await subscribe(session, job_id)
        await until(lambda: final_update(session))

        seen = [
            *subscribed.job_subscribed.log_lines,
            *(line for each in updates(session) for line in each.log_lines),
        ]
        assert "hello from the strategy" in seen

    in_one_loop(scenario())


@pytest.mark.integration
def test_cancel_job_stops_its_runs_and_marks_them_cancelled(tmp_path: Path) -> None:
    pid_file = tmp_path / "pid"

    async def scenario() -> None:
        _, jobs = real_jobs(tmp_path)
        session = Session(area.routes(jobs))
        table = run_table(params={"mode": "sleep", "out": str(pid_file)})
        job_id = submitted_job(await session.ask(submit_run(table)))
        await until(lambda: pid_file.read_text() or None if pid_file.exists() else None)
        pid = int(pid_file.read_text())

        reply = await session.ask(ClientMessage(cancel_job=CancelJob(job_id=job_id)))

        assert reply.WhichOneof("body") == "job_cancelled"
        [job] = jobs.list_jobs()
        assert job.state == JobState.JOB_STATE_CANCELLED
        assert states(job) == [RunStatus.RUN_STATUS_CANCELLED]
        await until(lambda: True if not alive(pid) else None, timeout=20)

    in_one_loop(scenario())


@pytest.mark.unit
def test_cancelling_an_unknown_job_answers_not_found() -> None:
    async def scenario() -> None:
        session = Session(area.routes(InMemoryJobs(FakeWorkers())))

        reply = await session.ask(ClientMessage(cancel_job=CancelJob(job_id="nope")))

        assert reply.error.code == ErrorCode.ERROR_CODE_NOT_FOUND

    in_one_loop(scenario())


@pytest.mark.unit
def test_cancelling_a_finished_job_does_nothing() -> None:
    async def scenario() -> None:
        workers = FakeWorkers(planning)
        jobs = InMemoryJobs(workers)
        session = Session(area.routes(jobs))
        job_id = submitted_job(await session.ask(submit_run(run_table())))
        [(_, worker)] = workers.launched
        worker.emit(Finished("run-1"), Finished("run-2"), Done(), Exited(0))
        await finished(jobs, job_id)

        reply = await session.ask(ClientMessage(cancel_job=CancelJob(job_id=job_id)))

        assert reply.WhichOneof("body") == "job_cancelled"
        assert not worker.stopped

    in_one_loop(scenario())


@pytest.mark.integration
def test_a_failing_run_marks_it_failed_with_its_reason_and_cancels_the_rest(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        _, jobs = real_jobs(tmp_path)
        session = Session(area.routes(jobs))
        params = {"mode": ["fail", "sleep"], "out": str(tmp_path / "pid")}
        reply = await session.ask(submit_run(run_table(params=params)))

        job = await finished(jobs, submitted_job(reply))

        assert job.state == JobState.JOB_STATE_FAILED
        failing, rest = job.runs
        assert failing.state == RunStatus.RUN_STATUS_FAILED
        assert "boom" in failing.reason
        assert rest.state == RunStatus.RUN_STATUS_CANCELLED

    in_one_loop(scenario())


@pytest.mark.unit
def test_jobs_run_one_at_a_time_in_submit_order() -> None:
    async def scenario() -> None:
        workers = FakeWorkers(planning)
        jobs = InMemoryJobs(workers)
        session = Session(area.routes(jobs))
        first = submitted_job(await session.ask(submit_run(run_table())))
        second = submitted_job(await session.ask(submit_run(run_table())))
        (_, running), (_, waiting) = workers.launched

        assert [each.job_id for each in jobs.list_jobs()] == [first, second]
        assert [each.state for each in jobs.list_jobs()] == [
            JobState.JOB_STATE_RUNNING,
            JobState.JOB_STATE_QUEUED,
        ]
        assert running.started
        assert not waiting.started

        running.emit(Done(), Exited(0))
        await until(lambda: True if waiting.started else None, timeout=5)

        assert [each.state for each in jobs.list_jobs()] == [
            JobState.JOB_STATE_FINISHED,
            JobState.JOB_STATE_RUNNING,
        ]

    in_one_loop(scenario())


@pytest.mark.unit
def test_list_jobs_answers_every_job_with_its_run_states() -> None:
    async def scenario() -> None:
        workers = FakeWorkers(planning)
        jobs = InMemoryJobs(workers)
        session = Session(area.routes(jobs))
        job_id = submitted_job(await session.ask(submit_run(run_table())))
        [(_, worker)] = workers.launched
        worker.emit(Started("run-1"))
        await until(
            lambda: (
                True
                if jobs.list_jobs()[0].runs[0].state == RunStatus.RUN_STATUS_RUNNING
                else None
            ),
            timeout=5,
        )

        reply = await session.ask(ClientMessage(list_jobs=ListJobs()))

        [job] = reply.jobs.jobs
        assert job.job_id == job_id
        assert job.state == JobState.JOB_STATE_RUNNING
        assert [(each.run_id, each.state) for each in job.runs] == [
            ("run-1", RunStatus.RUN_STATUS_RUNNING),
            ("run-2", RunStatus.RUN_STATUS_PENDING),
        ]

    in_one_loop(scenario())


@pytest.mark.unit
def test_a_failed_run_in_a_job_is_reported_with_its_reason() -> None:
    async def scenario() -> None:
        workers = FakeWorkers(planning)
        jobs = InMemoryJobs(workers)
        session = Session(area.routes(jobs))
        job_id = submitted_job(await session.ask(submit_run(run_table())))
        [(_, worker)] = workers.launched

        worker.emit(Started("run-1"), Failed("run-1", "it broke"), Exited(1))
        job = await finished(jobs, job_id)

        assert job.state == JobState.JOB_STATE_FAILED
        assert [(each.state, each.reason) for each in job.runs] == [
            (RunStatus.RUN_STATUS_FAILED, "it broke"),
            (RunStatus.RUN_STATUS_CANCELLED, ""),
        ]

    in_one_loop(scenario())


@pytest.mark.unit
def test_unsubscribe_stops_the_pushes() -> None:
    async def scenario() -> None:
        workers = FakeWorkers(planning)
        jobs = InMemoryJobs(workers)
        session = Session(area.routes(jobs, interval=0.01))
        job_id = submitted_job(await session.ask(submit_run(run_table())))
        [(_, worker)] = workers.launched
        subscribed = await subscribe(session, job_id)
        worker.emit(Started("run-1"))
        await until(lambda: updates(session) or None, timeout=5)

        reply = await session.ask(
            ClientMessage(
                unsubscribe=Unsubscribe(
                    subscription_id=subscribed.job_subscribed.subscription_id
                )
            )
        )
        before = len(session.pushes)
        worker.emit(Started("run-2"), Done(), Exited(0))
        await finished(jobs, job_id)
        await asyncio.sleep(0.1)

        assert reply.WhichOneof("body") == "unsubscribed"
        assert len(session.pushes) == before

    in_one_loop(scenario())


@pytest.mark.unit
def test_a_flood_of_log_lines_is_pushed_within_the_envelope_limit() -> None:
    lines = [f"{number:04} " + "x" * 5000 for number in range(1000)]
    emitted = [
        JobUpdate(log_lines=lines[at : at + 100], state=JobState.JOB_STATE_RUNNING)
        for at in range(0, len(lines), 100)
    ]
    emitted[-1].state = JobState.JOB_STATE_FINISHED
    emitted[-1].runs.add(run_id="run-1", state=RunStatus.RUN_STATUS_FINISHED)
    subscription = ScriptedSubscription(emitted)

    async def scenario() -> None:
        session = Session(area.routes(Static(subscription)))
        await subscribe(session, "job")
        await until(lambda: True if subscription.closed else None, timeout=20)
        pushes = session.pushes
        assert all(each.ByteSize() <= MAX_ENVELOPE for each in pushes)
        pushed = [each.job_update for each in pushes]
        assert [line for each in pushed for line in each.log_lines] == lines
        assert pushed[-1].state == JobState.JOB_STATE_FINISHED
        assert [each.run_id for each in pushed[-1].runs] == ["run-1"]

    in_one_loop(scenario())


@pytest.mark.unit
def test_an_over_long_log_line_is_truncated_and_a_stream_without_newline_is_bounded() -> (
    None
):
    lines = Lines()

    first = lines.feed(b"x" * (10 * LINE_LIMIT) + b"\nnext\n")
    for _ in range(50):
        assert lines.feed(b"y" * 1_000_000) == []
    last = lines.flush()

    assert len(first) == 2
    assert first[0].startswith("xxx")
    assert first[0].endswith("[truncated]")
    assert len(first[0]) <= LINE_LIMIT + 32
    assert first[1] == "next"
    assert len(last) == 1
    assert len(last[0]) <= LINE_LIMIT + 32


@pytest.mark.unit
def test_a_snapshot_drops_the_oldest_log_lines_until_it_fits() -> None:
    lines = [f"{number:03} " + "x" * 8000 for number in range(200)]
    subscription = ScriptedSubscription([], lines)

    async def scenario() -> None:
        session = Session(area.routes(Static(subscription)))
        reply = await subscribe(session, "job")
        kept = list(reply.job_subscribed.log_lines)
        assert reply.ByteSize() <= MAX_ENVELOPE
        assert 0 < len(kept) < 200
        assert kept == lines[-len(kept) :]
        await session.close()

    in_one_loop(scenario())


@pytest.mark.unit
def test_a_split_update_carries_the_job_state_in_its_last_push_only() -> None:
    update = JobUpdate(
        log_lines=["x" * 5000] * 600,
        state=JobState.JOB_STATE_FAILED,
        reason="broke",
    )
    update.runs.add(run_id="run-1", state=RunStatus.RUN_STATUS_FAILED)

    messages = update_messages(update, 7)

    assert len(messages) > 1
    assert all(each.subscription_id == 7 for each in messages)
    assert [each.job_update.state for each in messages[:-1]] == [
        JobState.JOB_STATE_UNSPECIFIED
    ] * (len(messages) - 1)
    assert messages[-1].job_update.state == JobState.JOB_STATE_FAILED
    assert messages[-1].job_update.reason == "broke"
    assert [r.run_id for each in messages for r in each.job_update.runs] == ["run-1"]
