"""Launchers that leave a child uncapped, recording the cap it would get."""

import subprocess
import sys
from collections.abc import Sequence
from typing import override

import pytest

from sbt2 import cli
from sbt2.run import Launcher, batching

CHILD = [sys.executable, "-m", "sbt2.run"]


class PlainLauncher(Launcher):
    def __init__(self) -> None:
        self.pids: list[int] = []
        self.caps: list[int] = []

    @override
    def check(self) -> None:
        pass

    @override
    def cap(self, run_id: str, pid: int, memory_max: int) -> None:
        self.pids.append(pid)
        self.caps.append(memory_max)

    @override
    def out_of_memory(self, run_id: str) -> bool:
        return False


def spawned(monkeypatch: pytest.MonkeyPatch) -> list[subprocess.Popen[bytes]]:
    """Records every child a batch spawns, each the real child."""
    children: list[subprocess.Popen[bytes]] = []

    def recorded() -> subprocess.Popen[bytes]:
        children.append(subprocess.Popen(CHILD, stdin=subprocess.PIPE))
        return children[-1]

    monkeypatch.setattr(batching, "_spawn", recorded)
    return children


class ScriptedLauncher(PlainLauncher):
    """Has the batch spawn the n-th child as the n-th of ``commands`` instead of
    the real one."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, commands: Sequence[Sequence[str]]
    ) -> None:
        super().__init__()
        self.started: list[subprocess.Popen[bytes]] = []
        self._commands = list(commands)
        monkeypatch.setattr(batching, "_spawn", self._spawn)

    def _spawn(self) -> subprocess.Popen[bytes]:
        command = self._commands[len(self.started)]
        self.started.append(self._popen(command))
        return self.started[-1]

    def _popen(self, command: Sequence[str]) -> subprocess.Popen[bytes]:
        return subprocess.Popen(command, stdin=subprocess.PIPE)


def uncapped(monkeypatch: pytest.MonkeyPatch) -> PlainLauncher:
    """Has ``sbt2 run`` start its children with a ``PlainLauncher``."""
    launcher = PlainLauncher()
    monkeypatch.setattr(cli, "launcher_for", lambda _: launcher)
    return launcher
