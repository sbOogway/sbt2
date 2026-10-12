from pathlib import Path

import pytest
from nautilus_trader.model import Money
from option_catalog import HOURS, START, TRADE_PRICE, build_option_catalog, mark_at

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "run_strategies:BuyOneOption"
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
BASE_FEE = 0.0003
CHECKED_FROM_HOUR = 4


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("option_catalog")
    build_option_catalog(path)
    return path


def run(tmp_path: Path, catalog: Path) -> tuple[ParquetResultStore, str]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog))
    return store, sink.run_id


def moves(store: ParquetResultStore, run_id: str) -> tuple[list[float], list[float]]:
    """The moves of the equity and of the mark price since the first checked hour."""
    frame = store.load(run_id, "equity")
    frame["hour"] = ((frame["ts_event"] - START).dt.total_seconds() // 3600).astype(int)
    kept = frame[(frame["hour"] >= CHECKED_FROM_HOUR) & (frame["hour"] < HOURS)]
    equity = kept["total_equity"].tolist()
    marks = [float(mark_at(hour)) for hour in kept["hour"]]
    return [each - equity[0] for each in equity], [each - marks[0] for each in marks]


@pytest.mark.integration
def test_a_run_on_a_deribit_option_values_its_position_at_the_mark_price(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog)

    [fill] = store.load(run_id, "fills").to_dict("records")
    assert Money.from_str(fill["commission"]).as_double() == pytest.approx(BASE_FEE)
    assert float(fill["last_px"]) == float(TRADE_PRICE)
    equity, marks = moves(store, run_id)
    assert equity == pytest.approx(marks)
