from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from sbt2.core.data import Source
from sbt2.core.results import ResultStore
from sbt2.core.run.batching.memory import Memory
from sbt2.core.run.execute import RunSettings
from sbt2.core.run.launchers import Launcher
from sbt2.core.run.preflighting import DataFolders


class BatchProgress(Protocol):
    def planned(self, runs: int, /) -> None: ...

    def finished(self, run_id: str, /) -> None: ...


@dataclass(frozen=True)
class BatchSetup:
    """Each child reopens ``store`` from its locator and opens its own sink."""

    store: ResultStore
    sources: Callable[[str], Source]
    folders: DataFolders
    settings: RunSettings
    launcher: Launcher
    memory: Memory = field(default_factory=Memory)
