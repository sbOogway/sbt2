"""Launchers that start a child as a plain subprocess, ignoring its memory cap."""

import subprocess
from collections.abc import Sequence

import pytest

from sbt2 import cli


class PlainLauncher:
    def __init__(self) -> None:
        self.started: list[subprocess.Popen[bytes]] = []
        self.caps: list[int] = []

    def check(self) -> None:
        pass

    def start(
        self, run_id: str, command: Sequence[str], memory_max: int
    ) -> subprocess.Popen[bytes]:
        child = subprocess.Popen(self._command(command), stdin=subprocess.PIPE)
        self.started.append(child)
        self.caps.append(memory_max)
        return child

    def out_of_memory(self, run_id: str) -> bool:
        return False

    def _command(self, command: Sequence[str]) -> Sequence[str]:
        return command


class ScriptedLauncher(PlainLauncher):
    """Starts the n-th child as the n-th of ``commands`` instead of the real one."""

    def __init__(self, commands: Sequence[Sequence[str]]) -> None:
        super().__init__()
        self._commands = list(commands)

    def _command(self, command: Sequence[str]) -> Sequence[str]:
        return self._commands[len(self.started)]


def uncapped(monkeypatch: pytest.MonkeyPatch) -> PlainLauncher:
    """Has ``sbt2 run`` start its children with a ``PlainLauncher``."""
    launcher = PlainLauncher()
    monkeypatch.setattr(cli, "SystemdScope", lambda: launcher)
    return launcher
