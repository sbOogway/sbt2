from typing import override

from sbt2.core.run.batching import Launcher
from sbt2.core.run.systemd import SystemdScope


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


_LAUNCHERS: tuple[type[Launcher], ...] = (SystemdScope, Uncapped)


class UnknownLauncherError(LookupError):
    pass


def launcher_named(name: str) -> Launcher:
    """The launcher called ``name``."""
    for each in _LAUNCHERS:
        if each.name == name:
            return each()
    known = ", ".join(sorted(each.name for each in _LAUNCHERS))
    raise UnknownLauncherError(f"no launcher {name}; known: {known}")
