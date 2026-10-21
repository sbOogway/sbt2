from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import ClassVar

from nautilus_trader.backtest import BacktestDataConfig
from nautilus_trader.model import BarSpecification

from sbt2.core.assets import QuoteJob


class BarSource(ABC):
    """What a run's declared bars are built from.

    ``name`` is how a spec file's ``bars`` names the source.
    ``aggregated_from`` names the external bars the declared bars are built
    from, or is ``None`` when they are built from ticks.
    """

    name: ClassVar[str]
    aggregated_from: ClassVar[str | None]

    @abstractmethod
    def data_types(self, inputs: Sequence[BarSpecification]) -> set[type]:
        """The data the ``inputs`` bars are built from."""

    @abstractmethod
    def write_fills(self, job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
        """Write the data the venue fills the run's orders on, beyond the data the
        run reads from its catalog, to a catalog in ``folder``, and return the data
        configs that stream it; none when it needs none."""
