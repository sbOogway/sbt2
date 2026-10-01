import os
import subprocess
import sys
import time
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import override

import pytest
from batch_kit import NEXT_DAY, GiB, resolved, served, setup, summaries
from launchers import PlainLauncher, ScriptedLauncher
from nautilus_trader.model import FundingRateUpdate
from served_source import INSTRUMENT_ID

from sbt2.data.sources import Gap
from sbt2.results import ParquetResultStore
from sbt2.run import Memory, MissingDataError, RunFailedError, batch

EXIT = [sys.executable, "-c", "pass"]
FAIL = [sys.executable, "-c", "raise SystemExit(1)"]
NAP = [sys.executable, "-c", "import time; time.sleep(0.5)"]
SLEEP = [sys.executable, "-c", "import time; time.sleep(60)"]


class RecordedProgress:
    def __init__(self) -> None:
        self.runs: list[int] = []
        self.done: list[str] = []

    def planned(self, runs: int) -> None:
        self.runs.append(runs)

    def finished(self, run_id: str) -> None:
        self.done.append(run_id)


class CountingLauncher(ScriptedLauncher):
    """Records the most children alive at once, counted as each one starts."""

    most_alive = 0

    @override
    def cap(self, run_id: str, pid: int, memory_max: int) -> None:
        super().cap(run_id, pid, memory_max)
        alive = sum(each.poll() is None for each in self.started)
        self.most_alive = max(self.most_alive, alive)


class PipelessLauncher(ScriptedLauncher):
    """Has the batch spawn each child without the stdin pipe its order goes
    through."""

    @override
    def _popen(self, command: Sequence[str]) -> subprocess.Popen[bytes]:
        return subprocess.Popen(command)


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

    batch(specs, setup(tmp_path, ScriptedLauncher(monkeypatch, [EXIT, EXIT])))

    assert not (tmp_path / "results").exists()


@pytest.mark.integration
def test_progress_counts_the_runs_planned_and_finished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    progress = RecordedProgress()
    specs = [
        resolved(tmp_path, params={"hold_bars": 2}),
        resolved(tmp_path, params={"hold_bars": 3}),
    ]

    run_ids = batch(
        specs, setup(tmp_path, ScriptedLauncher(monkeypatch, [EXIT, EXIT])), progress
    )

    assert progress.runs == [2]
    assert sorted(progress.done) == sorted(run_ids)


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
    launcher = ScriptedLauncher(monkeypatch, [FAIL, SLEEP, EXIT])
    started = time.monotonic()

    with pytest.raises(RunFailedError):
        batch(specs, setup(tmp_path, launcher))

    assert time.monotonic() - started < 30
    failed, sleeper = launcher.started
    assert failed.returncode == 1
    assert sleeper.returncode is not None
    assert sleeper.returncode < 0


@pytest.mark.integration
def test_at_most_budget_over_per_run_runs_go_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = [resolved(tmp_path, params={"hold_bars": each}) for each in (2, 3, 4, 5)]
    launcher = CountingLauncher(monkeypatch, [NAP] * 4)

    batch(specs, setup(tmp_path, launcher))

    assert launcher.most_alive == 2
    assert [each.returncode for each in launcher.started] == [0] * 4


@pytest.mark.unit
def test_a_budget_below_the_per_run_cap_is_refused() -> None:
    with pytest.raises(ValueError, match="budget"):
        Memory(budget=GiB, per_run=2 * GiB)


@pytest.mark.integration
def test_a_child_started_without_a_stdin_pipe_is_refused_and_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    launcher = PipelessLauncher(monkeypatch, [SLEEP])

    with pytest.raises(ValueError, match="without a stdin pipe"):
        batch([resolved(tmp_path)], setup(tmp_path, launcher))

    [child] = launcher.started
    assert child.returncode is not None
