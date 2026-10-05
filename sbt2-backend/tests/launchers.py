"""Launchers that leave a child uncapped, recording the cap it would get."""

import multiprocessing
import os
import signal
import time
from collections.abc import Callable, Sequence
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Event
from typing import override

import pytest

from sbt2.core.run import Launcher
from sbt2.core.run.batching import children as batch_children
from sbt2.core.run.child import run_child

type Script = Callable[[Connection], None]


def exits(_order: Connection) -> None:
    pass


def fails(_order: Connection) -> None:
    raise SystemExit(1)


def fails_when_ready(ready: Event, _order: Connection) -> None:
    if not ready.wait(10):
        raise TimeoutError("the other child did not become ready")
    raise SystemExit(1)


def resists_termination(ready: Event, _order: Connection) -> None:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    ready.set()
    time.sleep(60)


def naps(_order: Connection) -> None:
    time.sleep(0.5)


def sleeps(_order: Connection) -> None:
    time.sleep(60)


def killed(_order: Connection) -> None:
    os.kill(os.getpid(), signal.SIGKILL)


def forked(script: Script) -> tuple[BaseProcess, Connection]:
    """A child forked from the forkserver that runs ``script`` instead of its
    order, with the pipe its order goes through."""
    context = multiprocessing.get_context("forkserver")
    reader, writer = context.Pipe(duplex=False)
    child = context.Process(target=script, args=(reader,))
    child.start()
    reader.close()
    return child, writer


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


def spawned(monkeypatch: pytest.MonkeyPatch) -> list[BaseProcess]:
    """Records every child a batch spawns, each the real child."""
    children: list[BaseProcess] = []

    def recorded() -> tuple[BaseProcess, Connection]:
        child, pipe = forked(run_child)
        children.append(child)
        return child, pipe

    monkeypatch.setattr(batch_children, "_spawn", recorded)
    return children


class ScriptedLauncher(PlainLauncher):
    """Has the batch fork the n-th child to run the n-th of ``scripts`` instead
    of its order."""

    def __init__(
        self, monkeypatch: pytest.MonkeyPatch, scripts: Sequence[Script]
    ) -> None:
        super().__init__()
        self.started: list[BaseProcess] = []
        self._scripts = list(scripts)
        monkeypatch.setattr(batch_children, "_spawn", self._spawn)

    def _spawn(self) -> tuple[BaseProcess, Connection]:
        child, pipe = forked(self._scripts[len(self.started)])
        self.started.append(child)
        return child, pipe
