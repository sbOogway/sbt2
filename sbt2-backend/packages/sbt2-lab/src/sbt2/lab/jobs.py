from sbt2.lab.session import Session
from sbt2.protocol.v1.envelope_pb2 import ClientMessage
from sbt2.protocol.v1.runs_pb2 import Job, JobState, JobUpdate, SubscribeJob

_OVER = {
    JobState.JOB_STATE_FINISHED,
    JobState.JOB_STATE_FAILED,
    JobState.JOB_STATE_CANCELLED,
}


async def followed(session: Session, job_id: str) -> Job:
    """The job ``job_id`` once it is over."""
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
    if update.state != JobState.JOB_STATE_UNSPECIFIED:
        job.state = update.state
    if update.reason:
        job.reason = update.reason
