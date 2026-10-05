import pytest
from launchers import PlainLauncher

from sbt2.cli import run as cli


def uncapped(monkeypatch: pytest.MonkeyPatch) -> PlainLauncher:
    """Has ``sbt2 run`` start its children with a ``PlainLauncher``."""
    launcher = PlainLauncher()
    monkeypatch.setattr(cli, "launcher_named", lambda _: launcher)
    return launcher
