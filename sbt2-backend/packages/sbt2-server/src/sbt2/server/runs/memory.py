import asyncio
import logging
import uuid
from collections import deque
from collections.abc import AsyncIterator, Sequence
from typing import override

from sbt2.protocol.v1.runs_pb2 import (
    Job,
    JobState,
    JobSubmitted,
    JobUpdate,
    RunState,
    RunStatus,
)
from sbt2.protocol.v1.types_pb2 import StudyConflict, StudyConflictKind
from sbt2.server.runs.jobs import (
    InvalidSubmissionError,
    Jobs,
    NotFoundError,
    Submission,
    Subscription,
)
from sbt2.server.runs.wire import (
    Conflict,
    ConflictKind,
    Crashed,
    Done,
    Event,
    Exited,
    Failed,
    Finished,
    LogLines,
    Planned,
    Rejected,
    Rejection,
    Started,
)
from sbt2.server.runs.workers import Worker, Workers

LOG_LINES = 200

logger = logging.getLogger("sbt2.server")

_OVER = frozenset(
    {
        JobState.JOB_STATE_FINISHED,
        JobState.JOB_STATE_FAILED,
        JobState.JOB_STATE_CANCELLED,
    }
)
_SETTLED = frozenset({RunStatus.RUN_STATUS_FINISHED, RunStatus.RUN_STATUS_FAILED})


class InMemoryJobs(Jobs):
    """Jobs kept in memory for as long as the server runs, each in a worker.

    One job checks its specs at a time, so a submission answers as soon as its
    own specs are checked, and one job runs at a time, in the order they were
    submitted: a checked job is queued until the jobs before it are over.
    """

    def __init__(self, workers: Workers) -> None:
        self._workers = workers
        self._checking = asyncio.Lock()
        self._jobs: dict[str, _Job] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    @override
    async def submit(self, submission: Submission) -> JobSubmitted:
        async with self._checking:
            job = _Job(str(uuid.uuid7()), await self._workers.launch(submission))
            checked = asyncio.get_running_loop().create_future()
            self._follow(job, checked)
            try:
                run_ids = await checked
            except asyncio.CancelledError:
                await job.worker.stop()
                raise
            except Exception:
                await job.over.wait()
                raise
        return JobSubmitted(job_id=job.job_id, run_ids=run_ids)

    @override
    async def cancel(self, job_id: str) -> None:
        job = self._job(job_id)
        if job.state in _OVER:
            return
        job.cancelled = True
        await job.worker.stop()
        await job.over.wait()

    @override
    def list_jobs(self) -> list[Job]:
        return [job.snapshot() for job in self._jobs.values()]

    @override
    def subscribe(self, job_id: str) -> Subscription:
        return _Watch(self._job(job_id))

    def _job(self, job_id: str) -> _Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise NotFoundError(f"no job {job_id}")
        return job

    def _follow(self, job: _Job, checked: asyncio.Future[list[str]]) -> None:
        task = asyncio.create_task(self._apply_all(job, checked))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _apply_all(self, job: _Job, checked: asyncio.Future[list[str]]) -> None:
        async for event in job.worker.events():
            self._apply(job, event, checked)

    def _apply(
        self, job: _Job, event: Event, checked: asyncio.Future[list[str]]
    ) -> None:
        match event:
            case Planned(run_ids):
                self._accept(job, run_ids, checked)
            case Rejected(kind, message, conflict):
                _reject(checked, _rejection(kind, message, conflict))
            case Crashed(reason) if not checked.done():
                _reject(checked, RuntimeError(reason))
            case Exited(code):
                self._settle(job, code, checked)
            case _:
                job.apply(event)

    def _accept(
        self, job: _Job, run_ids: Sequence[str], checked: asyncio.Future[list[str]]
    ) -> None:
        job.plan(run_ids)
        self._jobs[job.job_id] = job
        if not checked.done():
            checked.set_result(list(run_ids))
        self._advance()

    def _settle(self, job: _Job, code: int, checked: asyncio.Future[list[str]]) -> None:
        _reject(
            checked,
            RuntimeError(
                f"the job process exited with code {code} before its specs were checked"
            ),
        )
        job.settle(code)
        self._advance()

    def _advance(self) -> None:
        for job in self._jobs.values():
            if job.state == JobState.JOB_STATE_RUNNING:
                return
            if job.state == JobState.JOB_STATE_QUEUED:
                job.run()
                return


class _Job:
    def __init__(self, job_id: str, worker: Worker) -> None:
        self.job_id = job_id
        self.worker = worker
        self.state: JobState.ValueType = JobState.JOB_STATE_CHECKING
        self.reason = ""
        self.cancelled = False
        self.over = asyncio.Event()
        self.logs: deque[str] = deque(maxlen=LOG_LINES)
        self.watches: set[_Watch] = set()
        self._runs: dict[str, RunState] = {}
        self._outcome: tuple[JobState.ValueType, str] | None = None

    def snapshot(self) -> Job:
        return Job(
            job_id=self.job_id,
            state=self.state,
            runs=[_copied(each) for each in self._runs.values()],
            reason=self.reason,
        )

    def plan(self, run_ids: Sequence[str]) -> None:
        self.state = JobState.JOB_STATE_QUEUED
        self._runs = {
            each: RunState(run_id=each, state=RunStatus.RUN_STATUS_PENDING)
            for each in run_ids
        }

    def run(self) -> None:
        self.state = JobState.JOB_STATE_RUNNING
        self.worker.start()
        self._publish()

    def apply(self, event: Event) -> None:
        match event:
            case Started(run_id):
                self._publish([self._set(run_id, RunStatus.RUN_STATUS_RUNNING)])
            case Finished(run_id):
                self._publish([self._set(run_id, RunStatus.RUN_STATUS_FINISHED)])
            case Failed(run_id, reason):
                self._outcome = (JobState.JOB_STATE_FAILED, "")
                failed = self._set(run_id, RunStatus.RUN_STATUS_FAILED, reason)
                self._publish([failed, *self._cancel_unsettled()])
            case Crashed(reason):
                self._outcome = (JobState.JOB_STATE_FAILED, reason)
            case Done():
                self._outcome = (JobState.JOB_STATE_FINISHED, "")
            case LogLines(lines):
                self.logs.extend(lines)
                self._publish(lines=lines)
            case _:
                pass

    def settle(self, code: int) -> None:
        self.state, self.reason = self._final(code)
        self._publish(self._cancel_unsettled())
        self.over.set()

    def _final(self, code: int) -> tuple[JobState.ValueType, str]:
        if self._outcome is not None:
            return self._outcome
        if self.cancelled:
            return JobState.JOB_STATE_CANCELLED, ""
        return JobState.JOB_STATE_FAILED, f"the job process exited with code {code}"

    def _set(
        self, run_id: str, state: RunStatus.ValueType, reason: str = ""
    ) -> RunState:
        run = self._runs[run_id]
        run.state, run.reason = state, reason
        return run

    def _cancel_unsettled(self) -> list[RunState]:
        return [
            self._set(each.run_id, RunStatus.RUN_STATUS_CANCELLED)
            for each in self._runs.values()
            if each.state not in _SETTLED
            and each.state != RunStatus.RUN_STATUS_CANCELLED
        ]

    def _publish(
        self, runs: Sequence[RunState] = (), lines: Sequence[str] = ()
    ) -> None:
        update = JobUpdate(
            runs=[_copied(each) for each in runs],
            log_lines=lines,
            state=self.state,
            reason=self.reason,
        )
        for watch in self.watches:
            watch.put(update)


class _Watch(Subscription):
    def __init__(self, job: _Job) -> None:
        super().__init__(job.snapshot(), list(job.logs))
        self._job = job
        self._queue = asyncio.Queue[JobUpdate]()
        if job.state in _OVER:
            self._queue.put_nowait(JobUpdate(state=job.state, reason=job.reason))
        else:
            job.watches.add(self)

    def put(self, update: JobUpdate) -> None:
        self._queue.put_nowait(update)

    @override
    async def updates(self) -> AsyncIterator[JobUpdate]:
        while True:
            update = await self._queue.get()
            yield update
            if update.state in _OVER:
                return

    @override
    def close(self) -> None:
        self._job.watches.discard(self)


def _copied(run: RunState) -> RunState:
    copy = RunState()
    copy.CopyFrom(run)
    return copy


def _rejection(kind: Rejection, message: str, conflict: Conflict | None) -> Exception:
    match kind:
        case Rejection.INVALID:
            return InvalidSubmissionError(message, _detail(conflict))
        case Rejection.NOT_FOUND:
            return NotFoundError(message)
        case _:
            logger.error("a job's specs could not be checked: %s", message)
            return RuntimeError(message)


_KINDS = {
    ConflictKind.CONTEXT: StudyConflictKind.STUDY_CONFLICT_KIND_CONTEXT,
    ConflictKind.CODE: StudyConflictKind.STUDY_CONFLICT_KIND_CODE,
    ConflictKind.DUPLICATE_RUN: StudyConflictKind.STUDY_CONFLICT_KIND_DUPLICATE_RUN,
}


def _detail(conflict: Conflict | None) -> StudyConflict | None:
    if conflict is None:
        return None
    return StudyConflict(
        kind=_KINDS[conflict.kind],
        context_keys=conflict.context_keys,
        run_id=conflict.run_id,
    )


def _reject(checked: asyncio.Future[list[str]], error: Exception) -> None:
    if not checked.done():
        checked.set_exception(error)
