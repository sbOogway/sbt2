import multiprocessing
import os
import signal
import time
import uuid
from collections.abc import Sequence
from functools import partial
from pathlib import Path
from typing import override

import pytest
from batch_kit import NEXT_DAY, GiB, resolved, served, setup, summaries
from launchers import (
    PlainLauncher,
    ScriptedLauncher,
    exits,
    fails,
    fails_when_ready,
    forked,
    killed,
    naps,
    resists_termination,
    sleeps,
)
from nautilus_trader.model import FundingRateUpdate

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import (
    Memory,
    MissingDataError,
    OutOfMemoryError,
    RunFailedError,
    Uncapped,
    batch,
)
from sbt2.core.run.batching import children as batch_children
from sbt2.data import Gap
from sbt2.data.testing import INSTRUMENT_ID

NAUTILUS_CORE = "_libnautilus"
FRESH = """
import os
from pathlib import Path

from run_strategies import BuyThenSell

with Path(__file__).with_name("imports.txt").open("a") as imports:
    imports.write(f"{os.getpid()} {VERSION}\\n")


class Fresh(BuyThenSell):
    pass
"""
HERE = """
from run_strategies import BuyThenSell


class Here(BuyThenSell):
    pass
"""


def fresh(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: str) -> str:
    """The import path of a strategy whose module records the pid and
    ``version`` of each process that imports it."""
    (tmp_path / "fresh.py").write_text(f"VERSION = {version!r}\n{FRESH}")
    monkeypatch.syspath_prepend(tmp_path)
    return "fresh:Fresh"


def imported(tmp_path: Path) -> dict[int, str]:
    """The version of the strategy each process imported, by its pid."""
    lines = (tmp_path / "imports.txt").read_text().splitlines()
    return {
        int(pid): version for pid, version in (each.split(maxsplit=1) for each in lines)
    }


def here(folder: Path) -> str:
    """The import path of a strategy whose module lives in ``folder``."""
    folder.mkdir()
    (folder / "here.py").write_text(HERE)
    return "here:Here"


class SlowLauncher(PlainLauncher):
    """Takes a while to cap each child, then records whether the child had
    already started its run."""

    def __init__(self, store: ParquetResultStore) -> None:
        super().__init__()
        self.store = store
        self.started_early: list[bool] = []

    @override
    def cap(self, run_id: str, pid: int, memory_max: int) -> None:
        super().cap(run_id, pid, memory_max)
        time.sleep(0.5)
        self.started_early.append(self.store.folder(run_id).exists())


class RecordedProgress:
    def __init__(self) -> None:
        self.planned_ids: list[tuple[str, ...]] = []
        self.events: list[tuple[str, str]] = []

    def planned(self, run_ids: Sequence[str]) -> None:
        self.planned_ids.append(tuple(run_ids))

    def started(self, run_id: str) -> None:
        self.events.append(("started", run_id))

    def finished(self, run_id: str) -> None:
        self.events.append(("finished", run_id))


class CountingLauncher(ScriptedLauncher):
    """Records the most children alive at once, counted as each one starts."""

    most_alive = 0

    @override
    def cap(self, run_id: str, pid: int, memory_max: int) -> None:
        super().cap(run_id, pid, memory_max)
        alive = sum(each.is_alive() for each in self.started)
        self.most_alive = max(self.most_alive, alive)


class InspectingLauncher(PlainLauncher):
    """Records each child's parent and whether it has nautilus's compiled core
    mapped, as the child waits for its order."""

    def __init__(self) -> None:
        super().__init__()
        self.parents: list[int] = []
        self.preloaded: list[bool] = []

    @override
    def cap(self, run_id: str, pid: int, memory_max: int) -> None:
        super().cap(run_id, pid, memory_max)
        proc = Path("/proc", str(pid))
        self.parents.append(int((proc / "stat").read_text().rsplit(")")[1].split()[1]))
        self.preloaded.append(NAUTILUS_CORE in (proc / "maps").read_text())


@pytest.mark.integration
def test_every_run_of_a_batch_is_stored_under_its_run_id(tmp_path: Path) -> None:
    specs = [
        resolved(tmp_path, params={"hold_bars": 2}),
        resolved(tmp_path, params={"hold_bars": 3}),
    ]

    run_ids = batch(specs, setup(tmp_path, PlainLauncher()))

    stored = summaries(tmp_path)
    assert [stored[each]["spec_hash"] for each in run_ids] == [
        each.hash for each in specs
    ]


@pytest.mark.integration
def test_a_run_writes_no_tearsheet(tmp_path: Path) -> None:
    run_ids = batch([resolved(tmp_path)], setup(tmp_path, PlainLauncher()))

    stored = [each for each in (tmp_path / "results").rglob("*") if each.is_file()]
    assert set(summaries(tmp_path)) == set(run_ids)
    assert stored
    assert not [each for each in stored if each.suffix == ".html"]


@pytest.mark.integration
def test_every_run_of_a_batch_shares_one_time_sortable_batch_id(
    tmp_path: Path,
) -> None:
    first = batch(
        [
            resolved(tmp_path, params={"hold_bars": 2}),
            resolved(tmp_path, params={"hold_bars": 3}),
        ],
        setup(tmp_path, PlainLauncher()),
    )
    second = batch([resolved(tmp_path)], setup(tmp_path, PlainLauncher()))

    stored = summaries(tmp_path)
    [first_id] = {stored[each]["batch_id"] for each in first}
    [second_id] = {stored[each]["batch_id"] for each in second}
    assert uuid.UUID(first_id).version == 7
    assert first_id < second_id


@pytest.mark.integration
def test_each_run_executes_in_its_own_fresh_process(tmp_path: Path) -> None:
    launcher = PlainLauncher()
    specs = [
        resolved(tmp_path, params={"hold_bars": 2}),
        resolved(tmp_path, params={"hold_bars": 3}),
    ]

    batch(specs, setup(tmp_path, launcher))

    pids = set(launcher.pids)
    assert len(pids) == 2
    assert os.getpid() not in pids


@pytest.mark.integration
def test_children_fork_from_one_forkserver_with_the_run_modules_loaded(
    tmp_path: Path,
) -> None:
    launcher = InspectingLauncher()
    specs = [
        resolved(tmp_path, params={"hold_bars": 2}),
        resolved(tmp_path, params={"hold_bars": 3}),
    ]

    batch(specs, setup(tmp_path, launcher))

    [parent] = set(launcher.parents)
    assert parent != os.getpid()
    assert launcher.preloaded == [True, True]


@pytest.mark.integration
def test_each_run_imports_its_strategy_afresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    strategy = fresh(tmp_path, monkeypatch, "first")
    first = PlainLauncher()
    specs = [
        resolved(tmp_path, strategy=strategy, params={"hold_bars": each})
        for each in (2, 3)
    ]
    batch(specs, setup(tmp_path, first))
    fresh(tmp_path, monkeypatch, "the edited one")
    second = PlainLauncher()

    batch(specs[:1], setup(tmp_path, second))

    versions = imported(tmp_path)
    assert len(set(first.pids)) == 2
    assert [versions[each] for each in first.pids] == ["first", "first"]
    assert [versions[each] for each in second.pids] == ["the edited one"]


@pytest.mark.integration
def test_a_child_runs_in_the_batch_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "b").mkdir()
    monkeypatch.chdir(tmp_path / "b")
    batch([resolved(tmp_path)], setup(tmp_path, PlainLauncher()))
    strategy = here(tmp_path / "a")
    monkeypatch.chdir(tmp_path / "a")
    monkeypatch.syspath_prepend("")

    [run_id] = batch(
        [resolved(tmp_path, strategy=strategy)], setup(tmp_path, PlainLauncher())
    )

    assert run_id in summaries(tmp_path)


@pytest.mark.integration
def test_a_child_does_no_work_until_its_launcher_has_capped_it(
    tmp_path: Path,
) -> None:
    launcher = SlowLauncher(ParquetResultStore(tmp_path / "results"))

    [run_id] = batch([resolved(tmp_path)], setup(tmp_path, launcher))

    assert launcher.started_early == [False]
    assert run_id in summaries(tmp_path)


@pytest.mark.integration
def test_known_gaps_found_by_preflight_are_stored_with_the_run(
    tmp_path: Path,
) -> None:
    gap = Gap(INSTRUMENT_ID, FundingRateUpdate, NEXT_DAY)
    source = served(frozenset({gap}))
    source.withdraw(FundingRateUpdate, NEXT_DAY)

    [run_id] = batch([resolved(tmp_path)], setup(tmp_path, PlainLauncher(), source))

    assert list(summaries(tmp_path)[run_id]["known_gaps"]) == [str(gap)]


@pytest.mark.integration
def test_a_run_failing_preflight_starts_no_run(tmp_path: Path) -> None:
    launcher = PlainLauncher()
    specs = [
        resolved(tmp_path),
        resolved(tmp_path, instruments=["ETHUSDT-LINEAR.BYBIT"]),
    ]

    with pytest.raises(MissingDataError):
        batch(specs, setup(tmp_path, launcher))

    assert launcher.pids == []
    assert not (tmp_path / "results").exists()


@pytest.mark.integration
def test_the_parent_writes_nothing_to_the_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = [
        resolved(tmp_path, params={"hold_bars": 2}),
        resolved(tmp_path, params={"hold_bars": 3}),
    ]

    batch(specs, setup(tmp_path, ScriptedLauncher(monkeypatch, [exits, exits])))

    assert not (tmp_path / "results").exists()


@pytest.mark.integration
def test_batch_progress_hears_planned_run_ids_then_started_and_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = RecordedProgress()
    specs = [
        resolved(tmp_path, params={"hold_bars": 2}),
        resolved(tmp_path, params={"hold_bars": 3}),
    ]

    run_ids = batch(
        specs, setup(tmp_path, ScriptedLauncher(monkeypatch, [exits, exits])), progress
    )

    assert progress.planned_ids == [run_ids]
    for run_id in run_ids:
        events = [each for each in progress.events if each[1] == run_id]
        assert events == [("started", run_id), ("finished", run_id)]


@pytest.mark.integration
def test_a_failed_run_raises_naming_its_run_its_folder_and_its_error(
    tmp_path: Path,
) -> None:
    spec = resolved(tmp_path, strategy="run_strategies:FailOnBar")
    store = ParquetResultStore(tmp_path / "results")

    with pytest.raises(RunFailedError) as failure:
        batch([spec], setup(tmp_path, PlainLauncher()))

    error = failure.value
    assert error.folder == store.folder(error.run_id)
    assert error.run_id in str(error)
    assert str(error.folder) in str(error)
    assert "strategy blew up" in str(error)
    assert (error.folder / "spec.json").exists()
    assert store.runs().empty


@pytest.mark.integration
def test_a_failure_stops_the_running_runs_and_starts_no_more(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = [resolved(tmp_path, params={"hold_bars": each}) for each in (2, 3, 4)]
    launcher = ScriptedLauncher(monkeypatch, [fails, sleeps, exits])
    started = time.monotonic()

    with pytest.raises(RunFailedError):
        batch(specs, setup(tmp_path, launcher))

    assert time.monotonic() - started < 30
    failed, sleeper = launcher.started
    assert failed.exitcode == 1
    assert sleeper.exitcode is not None
    assert sleeper.exitcode < 0


@pytest.mark.integration
def test_a_failure_kills_a_child_that_ignores_termination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = multiprocessing.get_context("forkserver").Event()
    scripts = [
        partial(fails_when_ready, ready),
        partial(resists_termination, ready),
        exits,
    ]
    launcher = ScriptedLauncher(monkeypatch, scripts)
    monkeypatch.setattr(batch_children, "_GRACE_SECONDS", 0.1)
    specs = [resolved(tmp_path, params={"hold_bars": each}) for each in (2, 3, 4)]
    started = time.monotonic()

    with pytest.raises(RunFailedError):
        batch(specs, setup(tmp_path, launcher))

    assert time.monotonic() - started < 30
    failed, resistant = launcher.started
    assert failed.exitcode == 1
    assert resistant.exitcode == -signal.SIGKILL


@pytest.mark.integration
def test_at_most_budget_over_per_run_runs_go_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = [resolved(tmp_path, params={"hold_bars": each}) for each in (2, 3, 4, 5)]
    launcher = CountingLauncher(monkeypatch, [naps] * 4)

    batch(specs, setup(tmp_path, launcher))

    assert launcher.most_alive == 2
    assert [each.exitcode for each in launcher.started] == [0] * 4


@pytest.mark.unit
def test_a_budget_below_the_per_run_cap_is_refused() -> None:
    with pytest.raises(ValueError, match="budget"):
        Memory(budget=GiB, per_run=2 * GiB)


@pytest.mark.integration
def test_an_uncapped_batch_runs_without_a_systemd_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    [run_id] = batch([resolved(tmp_path)], setup(tmp_path, Uncapped()))

    assert run_id in summaries(tmp_path)


@pytest.mark.integration
def test_an_uncapped_child_killed_by_a_signal_fails_with_its_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        batch_children,
        "_spawn",
        lambda: forked(killed),
    )

    with pytest.raises(RunFailedError) as failure:
        batch([resolved(tmp_path)], setup(tmp_path, Uncapped()))

    assert not isinstance(failure.value, OutOfMemoryError)
    assert "exited with code -9" in str(failure.value)
