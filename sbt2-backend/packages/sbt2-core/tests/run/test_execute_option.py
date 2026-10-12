import math
import shutil
from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model import Money
from option_catalog import HOURS, START, TRADE_PRICE, build_option_catalog, mark_at

from sbt2.core.assets import NoQuotesError
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
BALANCE = 1.0
OPEN_FROM_HOUR = 3
TICKS_PER_COIN = 10_000
HALF_SPREAD = 0.05
FAR_TRADE_PRICE = "0.2000"


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("option_catalog")
    build_option_catalog(path)
    return path


@pytest.fixture(scope="module")
def far_trade_catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("far_trade_catalog")
    build_option_catalog(path, FAR_TRADE_PRICE)
    return path


def run(tmp_path: Path, catalog: Path, strategy: str) -> tuple[ParquetResultStore, str]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC.replace("run_strategies:BuyOneOption", strategy))
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog))
    return store, sink.run_id


def open_equity(store: ParquetResultStore, run_id: str) -> dict[int, float]:
    """The equity by hour of the catalog, from when the position is open."""
    frame = store.load(run_id, "equity")
    frame["hour"] = ((frame["ts_event"] - START).dt.total_seconds() // 3600).astype(int)
    kept = frame[(frame["hour"] >= OPEN_FROM_HOUR) & (frame["hour"] < HOURS)]
    return dict(zip(kept["hour"], kept["total_equity"], strict=True))


def holding_value(side: int, hour: int, premium: float) -> float:
    """The coins a position of ``side`` contracts is worth: premium and mark."""
    return side * (float(mark_at(hour)) - premium)


def fill_of(store: ParquetResultStore, run_id: str) -> tuple[float, int]:
    """The price and the hour of the catalog of the run's only fill."""
    [fill] = store.load(run_id, "fills").to_dict("records")
    seconds = (pd.Timestamp(fill["ts_event"]) - START).total_seconds()
    return float(fill["last_px"]), int(seconds // 3600)


def synthetic_ask(hour: int) -> float:
    """The mark and half of 5 % of it up, rounded up to the tick, by hand."""
    ticks = float(mark_at(hour)) * TICKS_PER_COIN * (1 + HALF_SPREAD)
    return math.ceil(round(ticks, 2)) / TICKS_PER_COIN


@pytest.mark.integration
def test_a_run_on_a_deribit_option_values_its_position_at_the_mark_price(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog, "run_strategies:BuyOneOption")

    [fill] = store.load(run_id, "fills").to_dict("records")
    assert Money.from_str(fill["commission"]).as_double() == pytest.approx(BASE_FEE)
    premium, _ = fill_of(store, run_id)
    equity = open_equity(store, run_id)
    assert list(equity.values()) == pytest.approx(
        [BALANCE - BASE_FEE + holding_value(1, hour, premium) for hour in equity]
    )


@pytest.mark.integration
def test_a_run_short_a_deribit_option_values_its_liability_at_the_mark_price(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog, "run_strategies:SellOneOption")

    premium, _ = fill_of(store, run_id)
    equity = open_equity(store, run_id)
    assert list(equity.values()) == pytest.approx(
        [BALANCE - BASE_FEE + holding_value(-1, hour, premium) for hour in equity]
    )


@pytest.mark.integration
def test_an_option_market_buy_fills_at_the_synthetic_ask(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog, "run_strategies:BuyOneOption")

    price, hour = fill_of(store, run_id)
    assert price == pytest.approx(synthetic_ask(hour))
    assert price != pytest.approx(float(TRADE_PRICE))


@pytest.mark.integration
def test_an_option_trade_far_from_the_mark_does_not_set_the_fill_price(
    tmp_path: Path, far_trade_catalog: Path
) -> None:
    store, run_id = run(tmp_path, far_trade_catalog, "run_strategies:BuyOneOption")

    price, hour = fill_of(store, run_id)
    assert price == pytest.approx(synthetic_ask(hour))


@pytest.mark.integration
def test_an_option_run_without_index_prices_fails_naming_the_missing_data(
    tmp_path: Path, catalog: Path
) -> None:
    bare = tmp_path / "bare_catalog"
    shutil.copytree(catalog, bare)
    shutil.rmtree(bare / "data" / "index_prices")

    with pytest.raises(NoQuotesError, match="index"):
        run(tmp_path, bare, "run_strategies:BuyOneOption")
