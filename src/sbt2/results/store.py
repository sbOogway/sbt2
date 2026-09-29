from typing import Literal, Protocol

import pandas as pd

from sbt2.data.sources import Gap
from sbt2.results.sink import OutputSink
from sbt2.spec import ResolvedRunSpec

Table = Literal["equity", "carry", "fills", "positions", "account", "orders", "summary"]


class ResultStore(Protocol):
    def new_run(
        self, spec: ResolvedRunSpec, known_gaps: tuple[Gap, ...] = ()
    ) -> OutputSink:
        """A sink writing a new run, with a fresh run_id.

        ``known_gaps`` are the days of the run's data the source confirmed it lacks.
        """
        ...

    def runs(self) -> pd.DataFrame:
        """The summaries of every finished run, oldest first."""
        ...

    def load(self, run_id: str, table: Table) -> pd.DataFrame: ...

    def delete(self, run_id: str) -> None: ...


class UnknownRunError(LookupError):
    pass


class MissingTableError(LookupError):
    pass
