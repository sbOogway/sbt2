from pathlib import Path
from typing import Any, Literal, Protocol

import pandas as pd

from sbt2.data.sources import Gap
from sbt2.results.sink import OutputSink
from sbt2.spec import ResolvedRunSpec

Table = Literal["equity", "carry", "fills", "positions", "account", "orders", "summary"]


class ResultStore(Protocol):
    def new_run(
        self,
        spec: ResolvedRunSpec,
        known_gaps: tuple[Gap, ...] = (),
        run_id: str | None = None,
    ) -> OutputSink:
        """A sink writing a new run under ``run_id``, or a fresh one.

        ``known_gaps`` are the days of the run's data the source confirmed it lacks.
        """
        ...

    def runs(
        self, strategy: str | None = None, part: str | None = None
    ) -> pd.DataFrame:
        """The summaries of every finished run, oldest first.

        ``strategy`` and ``part``, when given, keep only the runs that match them.
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
