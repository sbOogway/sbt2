import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import pandas as pd

from sbt2.data.sources import Gap
from sbt2.results.sink import OutputSink
from sbt2.spec import ResolvedRunSpec

Table = Literal["equity", "carry", "fills", "positions", "account", "orders", "summary"]


@dataclass(frozen=True)
class Provenance:
    """Which code and data a run used, beyond what its spec asked for.

    ``known_gaps`` are the days of the run's data the source confirmed it lacks.
    """

    git_sha: str
    git_dirty: bool
    data_fingerprint: str | None = None
    known_gaps: tuple[Gap, ...] = ()

    @classmethod
    def of_repo(cls, repo: Path) -> Provenance:
        return cls(
            git_sha=_git(repo, "rev-parse", "HEAD"),
            git_dirty=bool(_git(repo, "status", "--porcelain")),
        )


class ResultStore(Protocol):
    def new_run(self, spec: ResolvedRunSpec, provenance: Provenance) -> OutputSink:
        """A sink writing a new run, with a fresh run_id."""
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


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
