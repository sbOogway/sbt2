from sbt2.lab.errors import JobFailedError
from sbt2.lab.session import Session
from sbt2.protocol.v1.envelope_pb2 import ClientMessage
from sbt2.protocol.v1.runs_pb2 import (
    Job,
    JobState,
    JobUpdate,
    RunStatus,
    SubscribeJob,
)

_OVER = {
    JobState.JOB_STATE_FINISHED,
    JobState.JOB_STATE_FAILED,
    JobState.JOB_STATE_CANCELLED,
}


async def finished(session: Session, job_id: str) -> None:
    """Wait for the job ``job_id`` to finish; raise if it fails or is cancelled."""
    job = await _over(session, job_id)
    if job.state != JobState.JOB_STATE_FINISHED:
        raise JobFailedError(_failure(job))


async def _over(session: Session, job_id: str) -> Job:
    request = ClientMessage(subscribe_job=SubscribeJob(job_id=job_id))
    [reply] = await session.ask(request)
    subscribed = reply.job_subscribed
    job = subscribed.job
    try:
        while job.state not in _OVER:
            _apply(job, (await session.push(subscribed.subscription_id)).job_update)
    finally:
        session.forget(subscribed.subscription_id)
    return job


def _apply(job: Job, update: JobUpdate) -> None:
    states = {each.run_id: each for each in job.runs}
    for changed in update.runs:
        if changed.run_id in states:
            states[changed.run_id].CopyFrom(changed)
        else:
            job.runs.append(changed)
            states[changed.run_id] = job.runs[-1]
    if update.state != JobState.JOB_STATE_UNSPECIFIED:
        job.state = update.state
    if update.reason:
        job.reason = update.reason


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
