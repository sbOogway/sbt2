import logging
from collections.abc import Iterable
from typing import Any

from tqdm.auto import tqdm

from sbt2.lab.errors import JobFailedError
from sbt2.lab.session import Session
from sbt2.protocol.v1.envelope_pb2 import ClientMessage
from sbt2.protocol.v1.runs_pb2 import (
    Job,
    JobState,
    JobSubmitted,
    JobUpdate,
    RunState,
    RunStatus,
    SubscribeJob,
)

logger = logging.getLogger("sbt2.lab")

_OVER = {
    JobState.JOB_STATE_FINISHED,
    JobState.JOB_STATE_FAILED,
    JobState.JOB_STATE_CANCELLED,
}
_RUN_OVER = {
    RunStatus.RUN_STATUS_FINISHED,
    RunStatus.RUN_STATUS_FAILED,
    RunStatus.RUN_STATUS_CANCELLED,
}


async def finished(session: Session, submitted: JobSubmitted) -> None:
    """Wait for the job to finish, showing its progress and logging its lines;
    raise if it fails or is cancelled."""
    with tqdm(total=len(submitted.run_ids), desc=submitted.job_id, unit="run") as bar:
        job = await _over(session, submitted.job_id, bar)
    if job.state != JobState.JOB_STATE_FINISHED:
        raise JobFailedError(_failure(job))


async def _over(session: Session, job_id: str, bar: tqdm[Any]) -> Job:
    request = ClientMessage(subscribe_job=SubscribeJob(job_id=job_id))
    [reply] = await session.ask(request)
    subscribed = reply.job_subscribed
    job = subscribed.job
    _log(subscribed.log_lines)
    _show(job, bar)
    try:
        while job.state not in _OVER:
            update = (await session.push(subscribed.subscription_id)).job_update
            _apply(job, update)
            _log(update.log_lines)
            _show(job, bar)
    finally:
        session.forget(subscribed.subscription_id)
    return job


def _apply(job: Job, update: JobUpdate) -> None:
    states = {each.run_id: each for each in job.runs}
    for changed in update.runs:
        _changed(job, states, changed)
    if update.state != JobState.JOB_STATE_UNSPECIFIED:
        job.state = update.state
    if update.reason:
        job.reason = update.reason


def _changed(job: Job, states: dict[str, RunState], changed: RunState) -> None:
    if changed.run_id in states:
        states[changed.run_id].CopyFrom(changed)
    else:
        job.runs.append(changed)
        states[changed.run_id] = job.runs[-1]


def _log(lines: Iterable[str]) -> None:
    for line in lines:
        logger.info(line)


def _show(job: Job, bar: tqdm[Any]) -> None:
    bar.n = sum(each.state in _RUN_OVER for each in job.runs)
    bar.refresh()


def _failure(job: Job) -> str:
    state = JobState.Name(job.state).removeprefix("JOB_STATE_").lower()
    reasons = [
        f"{each.run_id}: {each.reason}"
        for each in job.runs
        if each.state == RunStatus.RUN_STATUS_FAILED
    ]
    if job.reason:
        reasons.insert(0, job.reason)
    return f"job {job.job_id} {state}" + "".join(f"\n  {each}" for each in reasons)
