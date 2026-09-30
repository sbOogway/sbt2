from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

import pandas as pd

from sbt2.data import Gap
from sbt2.results.sink import OutputSink
from sbt2.spec import ResolvedRunSpec

Table = Literal["equity", "carry", "fills", "positions", "account", "orders", "summary"]


@dataclass(frozen=True)
class RunIds:
    """A new run's run_id, a fresh one when None, and the batch it belongs to."""

    run_id: str | None = None
    batch_id: str | None = None


class ResultStore(Protocol):
    def new_run(
        self,
        spec: ResolvedRunSpec,
        known_gaps: tuple[Gap, ...] = (),
        ids: RunIds | None = None,
    ) -> OutputSink:
        """A sink writing a new run under ``ids``, a fresh run_id outside a batch
        without them.

        ``known_gaps`` are the days of the run's data the source confirmed it lacks.
        """
        ...

    def runs(
        self,
        strategy: str | None = None,
        part: str | None = None,
        batch: str | None = None,
    ) -> pd.DataFrame:
        """The summaries of every finished run, oldest first.

        ``strategy``, ``part`` and ``batch``, when given, keep only the runs that
        match them.
        """
        ...

    def load(self, run_id: str, table: Table) -> pd.DataFrame: ...

    def spec(self, run_id: str) -> dict[str, Any]:
        """The resolved spec document of a run, finished or not."""
        ...

    def delete(self, run_id: str) -> None:
        """Remove the run, a failed run's partial folder included."""
        ...

    def folder(self, run_id: str) -> Path:
        """Where the run is written, whether or not it has started."""
        ...


class UnknownRunError(LookupError):
    pass


class MissingTableError(LookupError):
    pass
