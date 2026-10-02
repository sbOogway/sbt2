from abc import ABC, abstractmethod
from typing import ClassVar


class Launcher(ABC):
    """Starts each child of a batch under its memory cap, if it enforces one:
    a launcher that does not leaves memory to the machine or container.

    ``name`` is the name it is picked by.
    """

    name: ClassVar[str]

    @abstractmethod
    def check(self) -> None:
        """Raise if no child can be capped here."""

    @abstractmethod
    def cap(self, run_id: str, pid: int, memory_max: int) -> None:
        """Cap the running child ``pid``, which runs ``run_id``, at ``memory_max``
        bytes; it does no work until this returns."""

    @abstractmethod
    def out_of_memory(self, run_id: str) -> bool:
        """Whether the exited child running ``run_id`` was killed over its cap."""
