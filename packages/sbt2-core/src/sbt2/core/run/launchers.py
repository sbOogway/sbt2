from typing import override

from sbt2.core.run.batching import Launcher
from sbt2.core.run.systemd import SystemdScope


class Uncapped(Launcher):
    """Leaves each child's memory to whatever limits the machine or container
    sets."""

    @override
    def check(self) -> None:
        pass

    @override
    def cap(self, run_id: str, pid: int, memory_max: int) -> None:
        pass

    @override
    def out_of_memory(self, run_id: str) -> bool:
        return False


_LAUNCHERS: tuple[type[Launcher], ...] = (SystemdScope,)


class UnsupportedPlatformError(RuntimeError):
    pass


def launcher_for(platform: str) -> Launcher:
    """The launcher that caps each run's memory on ``platform``, a ``sys.platform``."""
    for each in _LAUNCHERS:
        if platform in each.platforms:
            return each()
    known = ", ".join(sorted(name for each in _LAUNCHERS for name in each.platforms))
    raise UnsupportedPlatformError(
        f"no launcher to cap each run's memory on {platform}; known: {known}"
    )
