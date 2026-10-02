from sbt2.core.run.launchers.base import Launcher
from sbt2.core.run.launchers.systemd import NoUserSessionError, SystemdScope
from sbt2.core.run.launchers.uncapped import Uncapped

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


__all__ = [
    "Launcher",
    "NoUserSessionError",
    "SystemdScope",
    "Uncapped",
    "UnknownLauncherError",
    "launcher_named",
]
