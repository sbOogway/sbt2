from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, Literal, Self

import pandas as pd

from sbt2.core.data import Catalog, Gap
from sbt2.core.results.metrics import RunTables
from sbt2.core.results.pricing import PricedRun
from sbt2.core.results.sink import OutputSink
from sbt2.core.spec import ResolvedRunSpec

Table = Literal["equity", "carry", "fills", "positions", "account", "orders", "summary"]


@dataclass(frozen=True)
class RunIds:
    """A new run's run_id, a fresh one when None, and the batch it belongs to."""

    run_id: str | None = None
    batch_id: str | None = None


@dataclass(frozen=True)
class RunFilter:
    """Keeps the runs matching every field given; None matches any run.

    ``run_ids`` keeps the runs it lists, so an empty one keeps none.
    """

    strategy: str | None = None
    part: str | None = None
    batch: str | None = None
    run_ids: tuple[str, ...] | None = None


_EVERY_RUN = RunFilter()


@dataclass(frozen=True)
class StoredRun:
    """A finished run as the store holds it, with the days its data skipped."""

    spec: ResolvedRunSpec
    tables: RunTables
    known_gaps: frozenset[Gap]

    def priced(self, catalog: Catalog) -> PricedRun:
        """The run valued from ``catalog``."""
        return PricedRun(self.spec, self.tables, catalog, self.known_gaps)


class ResultStore(ABC):
    """Where runs are written and read back.

    ``kind`` names the store in its locator, the JSON a run child reopens the
    store from with ``open_store``.
    """

    kind: ClassVar[str]

    def locator(self) -> dict[str, Any]:
        """Where the store lives, as JSON with its ``kind``."""
        return {"kind": self.kind, **self._location()}

    @classmethod
    @abstractmethod
    def from_location(cls, location: Mapping[str, Any]) -> Self:
        """The store at ``location``, a locator without its kind."""

    @abstractmethod
    def _location(self) -> dict[str, Any]:
        """Where the store lives, as JSON."""

    @abstractmethod
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

    @abstractmethod
    def runs(self, where: RunFilter = _EVERY_RUN) -> pd.DataFrame:
        """The summaries of the finished runs ``where`` keeps, oldest first."""

    @abstractmethod
    def load(self, run_id: str, table: Table) -> pd.DataFrame:
        """One table of the run."""

    @abstractmethod
    def stored_run(self, run_id: str) -> StoredRun:
        """The finished run, its spec rebuilt from its document; a run without a
        summary raises ``MissingTableError``."""

    @abstractmethod
    def spec(self, run_id: str) -> dict[str, Any]:
        """The resolved spec document of a run, finished or not."""

    @abstractmethod
    def delete(self, run_id: str) -> None:
        """Remove the run, a failed run's partial folder included."""

    @abstractmethod
    def folder(self, run_id: str) -> Path:
        """Where the run is written, whether or not it has started."""


class UnknownRunError(LookupError):
    pass


class MissingTableError(LookupError):
    pass
