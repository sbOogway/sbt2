from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from sbt2.server.runs.jobs import Submission
from sbt2.server.runs.wire import Event


class Worker(ABC):
    """One job's process, as the server sees it."""

    @abstractmethod
    def events(self) -> AsyncIterator[Event]:
        """What the job reports and prints, ending with ``Exited``."""

    @abstractmethod
    def start(self) -> None:
        """Tell a job that reported ``Planned`` to run its runs."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the job and its runs, and wait until it has exited."""


class Workers(ABC):
    """Where jobs run."""

    @abstractmethod
    async def launch(self, submission: Submission) -> Worker:
        """Start a job that checks the submission's specs."""
