from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from sbt2.protocol.v1.runs_pb2 import Job, JobSubmitted, JobUpdate
from sbt2.protocol.v1.types_pb2 import StudyConflict


class InvalidSubmissionError(ValueError):
    """A submission the server cannot run; its message says why. A run that
    does not fit its study also carries the ``conflict``."""

    def __init__(self, message: str, conflict: StudyConflict | None = None) -> None:
        super().__init__(message)
        self.conflict = conflict


class NotFoundError(LookupError):
    """A job, or a venue profile a submission names, that does not exist."""


@dataclass(frozen=True)
class Module:
    """A single-module strategy as the client uploaded it."""

    name: str
    source: str


@dataclass(frozen=True)
class Submission:
    """The spec file's table, and the module its strategy lives in."""

    spec: Mapping[str, Any]
    module: Module


class Subscription(ABC):
    """A job as it was when it was subscribed to, and what happens to it after."""

    def __init__(self, job: Job, log_lines: Sequence[str]) -> None:
        self.job = job
        self.log_lines = list(log_lines)

    @abstractmethod
    def updates(self) -> AsyncIterator[JobUpdate]:
        """The changes to the job, each carrying its state then; the last one
        carries a final state, and ends the iteration."""

    @abstractmethod
    def close(self) -> None:
        """Stop collecting updates."""


class Jobs(ABC):
    """The jobs the server runs: each is the runs one submitted spec expands
    into, run in a process of its own."""

    @abstractmethod
    async def submit(self, submission: Submission) -> JobSubmitted:
        """Check the submission's specs and queue its job. A submission that
        fails its checks raises ``InvalidSubmissionError`` or ``NotFoundError``
        and leaves no job."""

    @abstractmethod
    async def cancel(self, job_id: str) -> None:
        """Stop the job and cancel its unfinished runs; it does nothing for a job
        that is over. An unknown job raises ``NotFoundError``."""

    @abstractmethod
    def list_jobs(self) -> list[Job]:
        """Every job, in the order they were submitted."""

    @abstractmethod
    def subscribe(self, job_id: str) -> Subscription:
        """Follow the job; an unknown one raises ``NotFoundError``."""
