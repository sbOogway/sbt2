from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path

import pytest
from option_catalog import build_chain_catalog
from run_strategies import ActOnSchedule

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "run_strategies:ActOnSchedule"
instruments = ["BTC-OPTIONS.DERIBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
venue = "deribit_option"
capital = "1 BTC"
"""
VENUES = """
[deribit_option]
name = "DERIBIT"
source = "deribit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "OPTION"
fee_model = { kind = "capped_option", config = { maker_rate = "0.0003", taker_rate = "0.0003", cap_rate = "0.125" } }
"""


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("chain_catalog")
    build_chain_catalog(path)
    return path


def run(tmp_path: Path, catalog: Path, strategy: str) -> tuple[ParquetResultStore, str]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC.replace("run_strategies:ActOnSchedule", strategy))
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog))
    return store, sink.run_id


@pytest.mark.integration
def test_a_chain_strategy_acts_on_its_schedule_without_bars(
    tmp_path: Path, catalog: Path
) -> None:
    ActOnSchedule.ticks.clear()

    run(tmp_path, catalog, "run_strategies:ActOnSchedule")

    ticks = ActOnSchedule.ticks
    assert ticks[0] == datetime(2024, 1, 1, 3, tzinfo=UTC)
    assert {later - earlier for earlier, later in pairwise(ticks)} == {
        timedelta(hours=1)
    }
    assert ticks[-1] >= datetime(2024, 1, 2, 22, tzinfo=UTC)
