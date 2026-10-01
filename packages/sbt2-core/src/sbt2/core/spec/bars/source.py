from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import ClassVar

from nautilus_trader.model import BarSpecification


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
