from decimal import Decimal
from pathlib import Path

import pytest
from option_catalog import HOURS, OPTION_ID, START, build_option_catalog, mark_at
from run_strategies import ReadOrderMargin, ReadPositionMargin, SellTenOptions

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "run_strategies:SellOneOption"
instruments = ["BTC-1FEB24-50000-C.DERIBIT"]
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
HOUR_NS = 3_600 * 10**9
START_NS = int(START.timestamp()) * 10**9
FLOOR = Decimal("0.1")


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("option_catalog")
    build_option_catalog(path)
    return path


def run(tmp_path: Path, catalog: Path, strategy: str) -> tuple[ParquetResultStore, str]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC.replace("run_strategies:SellOneOption", strategy))
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog))
    return store, sink.run_id


def short_call_margin(ts: int) -> Decimal:
    """The floor plus the last mark at or before ``ts``: the call is far out of
    the money, so the floor is the larger term. The catalog's last mark is at
    its last hour."""
    hour = min((ts - START_NS) // HOUR_NS, HOURS - 1)
    return FLOOR + mark_at(hour)


@pytest.mark.integration
def test_a_strategy_reads_the_margin_of_an_order_before_it_sends_it(
    tmp_path: Path, catalog: Path
) -> None:
    ReadOrderMargin.asked.clear()

    run(tmp_path, catalog, "run_strategies:ReadOrderMargin")

    [(ts, margin)] = ReadOrderMargin.asked
    assert margin == short_call_margin(ts)


@pytest.mark.integration
def test_a_strategy_reads_the_margin_of_its_open_position(
    tmp_path: Path, catalog: Path
) -> None:
    ReadPositionMargin.read.clear()

    run(tmp_path, catalog, "run_strategies:ReadPositionMargin")

    assert len(ReadPositionMargin.read) > 1
    for ts, margins in ReadPositionMargin.read:
        assert margins == {str(OPTION_ID): short_call_margin(ts)}


@pytest.mark.integration
def test_a_short_option_order_beyond_the_free_equity_is_refused(
    tmp_path: Path, catalog: Path
) -> None:
    SellTenOptions.refused.clear()

    store, run_id = run(tmp_path, catalog, "run_strategies:SellTenOptions")

    [(instrument, reason)] = SellTenOptions.refused
    assert instrument == str(OPTION_ID)
    assert "initial margin of 1.52" in reason
    assert "free equity 1" in reason
    assert store.load(run_id, "fills").empty
