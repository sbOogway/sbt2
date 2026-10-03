from typing import override

from sbt2.core.run.launchers.base import Launcher


class Uncapped(Launcher):
    """Leaves each child's memory to whatever limits the machine or container
    sets."""

    name = "uncapped"

    @override
    def check(self) -> None:
        pass

    @override
    def cap(self, run_id: str, pid: int, memory_max: int) -> None:
        pass

    @override
    def out_of_memory(self, run_id: str) -> bool:
        return False
