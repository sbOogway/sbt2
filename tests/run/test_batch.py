import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from launchers import PlainLauncher, ScriptedLauncher
from nautilus_trader.model import FundingRateUpdate
from served_source import INSTRUMENT_ID, ServedSource

from sbt2.data.sources import Gap
from sbt2.results import ParquetResultStore
from sbt2.run import (
    BatchSetup,
    DataFolders,
    Launcher,
    Memory,
    MissingDataError,
    RunSettings,
    batch,
)
from sbt2.spec import ResolvedRunSpec, load

SPEC = """
strategy = "run_strategies:BuyThenSell"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
venue = "served_linear"
capital = "10000 USDT"
"""
VENUES = """
[served_linear]
name = "BYBIT"
source = "served"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
default_leverage = "10"
fee_model = { path = "nautilus_trader.execution:MakerTakerFeeModel", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }
"""
DAY = date(2024, 1, 1)
NEXT_DAY = date(2024, 1, 2)
GiB = 2**30
EXIT = [sys.executable, "-c", "pass"]


class RecordedProgress:
    def __init__(self) -> None:
        self.runs: list[int] = []
        self.done: list[str] = []

    def planned(self, runs: int) -> None:
        self.runs.append(runs)

    def finished(self, run_id: str) -> None:
        self.done.append(run_id)


def resolved(tmp_path: Path, **overrides: Any) -> ResolvedRunSpec:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)
    venues.write_text(VENUES)
    [resolved] = load(spec, overrides, venues)
    return resolved


def served(known_gaps: frozenset[Gap] = frozenset()) -> ServedSource:
    source = ServedSource(known_gaps)
    source.serve(DAY, NEXT_DAY)
    return source


def setup(
    tmp_path: Path, launcher: Launcher, source: ServedSource | None = None
) -> BatchSetup:
    data = DataFolders(tmp_path / "raw", tmp_path / "catalog")
    return BatchSetup(
        store=ParquetResultStore(tmp_path / "results"),
        sources=lambda name: source or served(),
        folders=data,
        settings=RunSettings(data.catalog),
        launcher=launcher,
        memory=Memory(budget=2 * GiB, per_run=GiB),
    )


def summaries(tmp_path: Path) -> dict[str, dict[str, Any]]:
    runs = ParquetResultStore(tmp_path / "results").runs()
    return {each["run_id"]: each for each in runs.to_dict("records")}


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
def test_each_run_executes_in_its_own_fresh_process(tmp_path: Path) -> None:
    launcher = PlainLauncher()
    specs = [
        resolved(tmp_path, params={"hold_bars": 2}),
        resolved(tmp_path, params={"hold_bars": 3}),
    ]

    batch(specs, setup(tmp_path, launcher))

    pids = {each.pid for each in launcher.started}
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

    assert launcher.started == []
    assert not (tmp_path / "results").exists()


@pytest.mark.integration
def test_the_parent_writes_nothing_to_the_store(tmp_path: Path) -> None:
    specs = [
        resolved(tmp_path, params={"hold_bars": 2}),
        resolved(tmp_path, params={"hold_bars": 3}),
    ]

    batch(specs, setup(tmp_path, ScriptedLauncher([EXIT, EXIT])))

    assert not (tmp_path / "results").exists()


@pytest.mark.integration
def test_progress_counts_the_runs_planned_and_finished(tmp_path: Path) -> None:
    progress = RecordedProgress()
    specs = [
        resolved(tmp_path, params={"hold_bars": 2}),
        resolved(tmp_path, params={"hold_bars": 3}),
    ]

    run_ids = batch(specs, setup(tmp_path, ScriptedLauncher([EXIT, EXIT])), progress)

    assert progress.runs == [2]
    assert sorted(progress.done) == sorted(run_ids)
