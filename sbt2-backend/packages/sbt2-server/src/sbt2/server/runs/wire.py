"""What the server and a job process say to each other, as JSON lines on the
job's own channel.

The server sends the job request first, and ``go`` when the job's turn comes.
The job process reports its events; the server adds the ones it sees itself,
``LogLines`` and ``Exited``.
"""

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

GO = "go"


class Rejection(StrEnum):
    """Why a job's specs were not accepted."""

    INVALID = "invalid"
    NOT_FOUND = "not_found"
    INTERNAL = "internal"


@dataclass(frozen=True)
class JobRequest:
    """What a job process runs: ``spec`` is the spec file's table, with its
    datetimes as ISO strings."""

    data_root: str
    venues: str
    module_name: str
    module_source: str
    spec: dict[str, Any]

    def to_line(self) -> str:
        return json.dumps(asdict(self), default=_iso)

    @classmethod
    def from_line(cls, line: str) -> JobRequest:
        return cls(**json.loads(line))


@dataclass(frozen=True)
class Planned:
    """Every spec is checked, and the job waits for ``go``."""

    run_ids: tuple[str, ...]


@dataclass(frozen=True)
class Rejected:
    kind: Rejection
    message: str


@dataclass(frozen=True)
class Started:
    run_id: str


@dataclass(frozen=True)
class Finished:
    run_id: str


@dataclass(frozen=True)
class Failed:
    run_id: str
    reason: str


@dataclass(frozen=True)
class Crashed:
    reason: str


@dataclass(frozen=True)
class Done:
    pass


@dataclass(frozen=True)
class LogLines:
    lines: tuple[str, ...]


@dataclass(frozen=True)
class Exited:
    code: int


type Event = (
    Planned
    | Rejected
    | Started
    | Finished
    | Failed
    | Crashed
    | Done
    | LogLines
    | Exited
)

_DECODERS: dict[str, Callable[[dict[str, Any]], Event]] = {
    "planned": lambda each: Planned(tuple(each["run_ids"])),
    "rejected": lambda each: Rejected(Rejection(each["kind"]), each["message"]),
    "started": lambda each: Started(each["run_id"]),
    "finished": lambda each: Finished(each["run_id"]),
    "failed": lambda each: Failed(each["run_id"], each["reason"]),
    "crashed": lambda each: Crashed(each["reason"]),
    "done": lambda _each: Done(),
}


def encode(event: Event) -> str:
    return json.dumps({"type": type(event).__name__.lower(), **asdict(event)})


def decode(line: str) -> Event:
    payload = json.loads(line)
    return _DECODERS[payload.pop("type")](payload)


def _iso(value: Any) -> str:
    return value.isoformat()
