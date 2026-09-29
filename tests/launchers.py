"""Launchers that start a child as a plain subprocess, without a memory cap."""

import subprocess
from collections.abc import Sequence


class PlainLauncher:
    def __init__(self) -> None:
        self.started: list[subprocess.Popen[bytes]] = []

    def check(self) -> None:
        pass

    def start(self, run_id: str, command: Sequence[str]) -> subprocess.Popen[bytes]:
        child = subprocess.Popen(self._command(command), stdin=subprocess.PIPE)
        self.started.append(child)
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
