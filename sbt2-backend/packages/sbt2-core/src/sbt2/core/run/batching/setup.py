from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol, Self

from nautilus_trader.common import LogLevel

from sbt2 import data
from sbt2.core.config import Root
from sbt2.core.results import ResultStore, store_at
from sbt2.core.run.batching.memory import Memory
from sbt2.core.run.execute import RunSettings
from sbt2.core.run.launchers import Launcher
from sbt2.core.run.preflighting import DataFolders
from sbt2.data import Source


class BatchProgress(Protocol):
    """Hears of each run: planned with the others, started, then finished. A run
    that fails or is stopped never finishes."""

    def planned(self, run_ids: Sequence[str], /) -> None: ...

    def started(self, run_id: str, /) -> None: ...

    def finished(self, run_id: str, /) -> None: ...


@dataclass(frozen=True)
class Launch:
    """How a batch starts its runs, and the memory they share."""

    launcher: Launcher
    memory: Memory = field(default_factory=Memory)


@dataclass(frozen=True)
class BatchSetup:
    """Each child reopens ``store`` from its locator and opens its own sink."""

    store: ResultStore
    sources: Callable[[str], Source]
    folders: DataFolders
    settings: RunSettings
    launcher: Launcher
    memory: Memory = field(default_factory=Memory)

    @classmethod
    def at(cls, root: Root, launch: Launch, log_level: LogLevel) -> Self:
        """Runs reading the data under ``root`` and storing their results there."""
        return cls(
            store=store_at(root),
            sources=lambda name: data.source(name, root.known_gaps),
            folders=DataFolders(root.raw, root.catalog),
            settings=RunSettings(root.catalog, log_level=log_level),
            launcher=launch.launcher,
            memory=launch.memory,
        )
