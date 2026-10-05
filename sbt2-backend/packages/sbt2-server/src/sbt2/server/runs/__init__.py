import asyncio
import itertools
from dataclasses import dataclass, field
from functools import wraps

from sbt2.core.config import ConfigFolder, Root
from sbt2.protocol.v1.envelope_pb2 import ClientMessage, ServerMessage
from sbt2.protocol.v1.runs_pb2 import (
    JobCancelled,
    JobSubscribed,
    JobUpdate,
    RunState,
    Unsubscribed,
)
from sbt2.protocol.v1.runs_pb2 import Jobs as JobList
from sbt2.protocol.v1.types_pb2 import Error, ErrorCode, StudyConflict
from sbt2.server import Handler, Outbox
from sbt2.server.runs.encoding import InvalidArgumentError, submission
from sbt2.server.runs.jobs import (
    InvalidSubmissionError,
    Jobs,
    NotFoundError,
    Subscription,
)
from sbt2.server.runs.memory import InMemoryJobs
from sbt2.server.runs.process import ProcessWorkers
from sbt2.server.runs.pushes import recent_lines, update_messages

PUSH_INTERVAL = 0.25


def local_jobs(root: Root, config: ConfigFolder) -> Jobs:
    """Jobs kept in memory, each run in a process of its own that reads and
    writes the data under ``root`` and reads the venue profiles in ``config``."""
    return InMemoryJobs(ProcessWorkers(root, config))


def routes(jobs: Jobs, interval: float = PUSH_INTERVAL) -> dict[str, Handler]:
    """Handlers for submitting, cancelling, listing and following ``jobs``; a
    subscription pushes at most one update every ``interval`` seconds."""
    runs = _Runs(jobs, interval)
    return {
        "submit_run": _guard(runs.submit_run),
        "cancel_job": _guard(runs.cancel_job),
        "list_jobs": _guard(runs.list_jobs),
        "subscribe_job": _guard(runs.subscribe_job),
        "unsubscribe": _guard(runs.unsubscribe),
    }


@dataclass
class _Subscribed:
    outbox: Outbox
    task: asyncio.Task[None]


@dataclass
class _Runs:
    jobs: Jobs
    interval: float
    ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))
    subscriptions: dict[int, _Subscribed] = field(default_factory=dict)

    async def submit_run(
        self, request: ClientMessage, _outbox: Outbox
    ) -> ServerMessage:
        submitted = await self.jobs.submit(submission(request.submit_run))
        return ServerMessage(job_submitted=submitted)

    async def cancel_job(
        self, request: ClientMessage, _outbox: Outbox
    ) -> ServerMessage:
        await self.jobs.cancel(request.cancel_job.job_id)
        return ServerMessage(job_cancelled=JobCancelled())

    async def list_jobs(
        self, _request: ClientMessage, _outbox: Outbox
    ) -> ServerMessage:
        return ServerMessage(jobs=JobList(jobs=self.jobs.list_jobs()))

    async def subscribe_job(
        self, request: ClientMessage, outbox: Outbox
    ) -> ServerMessage:
        subscription = self.jobs.subscribe(request.subscribe_job.job_id)
        subscription_id = next(self.ids)
        # the task runs only after this reply is queued: nothing here awaits
        task = outbox.spawn(self._push(subscription, subscription_id, outbox))
        self.subscriptions[subscription_id] = _Subscribed(outbox, task)
        task.add_done_callback(lambda _: self.subscriptions.pop(subscription_id, None))
        return ServerMessage(
            job_subscribed=JobSubscribed(
                subscription_id=subscription_id,
                job=subscription.job,
                log_lines=recent_lines(subscription.job, subscription.log_lines),
            )
        )

    async def unsubscribe(
        self, request: ClientMessage, outbox: Outbox
    ) -> ServerMessage:
        subscribed = self.subscriptions.get(request.unsubscribe.subscription_id)
        if subscribed is not None and subscribed.outbox is outbox:
            subscribed.task.cancel()
        return ServerMessage(unsubscribed=Unsubscribed())

    async def _push(
        self, subscription: Subscription, subscription_id: int, outbox: Outbox
    ) -> None:
        merged = _Merged()
        woken = asyncio.Event()
        collecting = asyncio.create_task(_collect(subscription, merged, woken))
        try:
            while True:
                await woken.wait()
                woken.clear()
                over = collecting.done()
                if merged.pending:
                    for message in update_messages(merged.take(), subscription_id):
                        outbox.push(message)
                if over:
                    return
                await asyncio.sleep(self.interval)
        finally:
            collecting.cancel()
            subscription.close()


class _Merged:
    """The updates collected since the last push, as one update."""

    def __init__(self) -> None:
        self.pending = False
        self._runs: dict[str, RunState] = {}
        self._lines: list[str] = []
        self._latest = JobUpdate()

    def add(self, update: JobUpdate) -> None:
        for run in update.runs:
            self._runs[run.run_id] = run
        self._lines.extend(update.log_lines)
        self._latest = update
        self.pending = True

    def take(self) -> JobUpdate:
        merged = JobUpdate(
            runs=list(self._runs.values()),
            log_lines=self._lines,
            state=self._latest.state,
            reason=self._latest.reason,
        )
        self._runs, self._lines, self.pending = {}, [], False
        return merged


async def _collect(
    subscription: Subscription, merged: _Merged, woken: asyncio.Event
) -> None:
    try:
        async for update in subscription.updates():
            merged.add(update)
            woken.set()
    finally:
        woken.set()


def _guard(handler: Handler) -> Handler:
    @wraps(handler)
    async def answer(request: ClientMessage, outbox: Outbox) -> ServerMessage:
        try:
            return await handler(request, outbox)
        except NotFoundError as error:
            return _error(ErrorCode.ERROR_CODE_NOT_FOUND, error)
        except InvalidSubmissionError as error:
            return _invalid(error, error.conflict)
        except InvalidArgumentError as error:
            return _invalid(error, None)

    return answer


def _error(code: ErrorCode.ValueType, error: Exception) -> ServerMessage:
    return ServerMessage(error=Error(code=code, message=str(error)))


def _invalid(error: Exception, conflict: StudyConflict | None) -> ServerMessage:
    reply = _error(ErrorCode.ERROR_CODE_INVALID_ARGUMENT, error)
    if conflict is not None:
        reply.error.study_conflict.CopyFrom(conflict)
    return reply


__all__ = ["local_jobs", "routes"]
