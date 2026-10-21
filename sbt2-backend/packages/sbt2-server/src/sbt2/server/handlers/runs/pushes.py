from collections.abc import Sequence

from sbt2.protocol.v1.envelope_pb2 import ServerMessage
from sbt2.protocol.v1.runs_pb2 import Job, JobUpdate
from sbt2.server.limits import MAX_ENVELOPE

# room for the envelope's own fields, the job state and the length prefixes
_SLACK = 512
_ITEM_OVERHEAD = 8


def update_messages(update: JobUpdate, subscription_id: int) -> list[ServerMessage]:
    """``update`` as pushes of ``subscription_id`` that each fit an envelope: log
    lines first, then run states; the job state is in the last one."""
    messages = [_empty(subscription_id)]
    used = 0

    def room_for(size: int) -> JobUpdate:
        nonlocal used
        if used and used + size > MAX_ENVELOPE - _SLACK:
            messages.append(_empty(subscription_id))
            used = 0
        used += size + _ITEM_OVERHEAD
        return messages[-1].job_update

    for line in update.log_lines:
        room_for(len(line.encode())).log_lines.append(line)
    for run in update.runs:
        room_for(run.ByteSize()).runs.append(run)
    last = messages[-1].job_update
    last.state, last.reason = update.state, update.reason
    return messages


def recent_lines(job: Job, lines: Sequence[str]) -> list[str]:
    """The newest of ``lines`` that fit a snapshot of ``job`` in one envelope."""
    room = MAX_ENVELOPE - _SLACK - job.ByteSize()
    kept: list[str] = []
    for line in reversed(lines):
        room -= len(line.encode()) + _ITEM_OVERHEAD
        if room < 0:
            break
        kept.append(line)
    return kept[::-1]


def _empty(subscription_id: int) -> ServerMessage:
    return ServerMessage(subscription_id=subscription_id, job_update=JobUpdate())
