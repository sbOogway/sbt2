from decimal import Decimal
from pathlib import Path

import pytest
from combo_strategies import OpenStrangle
from option_catalog import build_ladder_catalog, chain_contract_id

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "combo_strategies:OpenStrangle"
instruments = ["BTC-OPTIONS.DERIBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
venue = "deribit_option"
capital = "1 BTC"

[chain]
min_dte = 0
max_dte = 90
strike_band = "0.5"
"""
VENUES = """
[deribit_option]
name = "DERIBIT"
source = "deribit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "OPTION"
fee_model = { kind = "capped_option", config = { maker_rate = "0.0003", taker_rate = "0.0003", cap_rate = "0.125" } }
"""
PUT = str(chain_contract_id("12JAN24", 40000, "P"))
CALL = str(chain_contract_id("12JAN24", 50000, "C"))


@pytest.fixture(scope="module")
def ladder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("ladder_catalog")
    build_ladder_catalog(path)
    return path


def run(tmp_path: Path, catalog: Path, strategy: str) -> tuple[ParquetResultStore, str]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC.replace("combo_strategies:OpenStrangle", strategy))
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog, max_chain_contracts=2_000))
    return store, sink.run_id


def tags_of_fills(store: ParquetResultStore, run_id: str) -> list[list[str]]:
    """The tags of the order of each fill."""
    orders = store.load(run_id, "orders").set_index("venue_order_id")["tags"]
    fills = store.load(run_id, "fills")
    return [list(orders[each]) for each in fills["venue_order_id"]]


@pytest.mark.integration
def test_a_strategy_opens_a_strangle_as_one_combo(tmp_path: Path, ladder: Path) -> None:
    OpenStrangle.clear()

    store, run_id = run(tmp_path, ladder, "combo_strategies:OpenStrangle")

    fills = store.load(run_id, "fills")
    assert sorted(fills["instrument_id"]) == sorted([PUT, CALL])
    assert set(fills["order_side"]) == {"SELL"}
    [opened] = OpenStrangle.opened
    assert opened.id == "C1"
    assert opened.name == "short strangle"
    by_leg = {each.contract.id.value: each.price for each in opened.legs}
    prices = {
        row["instrument_id"]: Decimal(str(row["last_px"]))
        for row in fills.to_dict("records")
    }
    assert by_leg == prices
    assert opened.credit == sum(prices.values())
    assert tags_of_fills(store, run_id) == [["COMBO:C1"], ["COMBO:C1"]]
    [seen] = {ids for _, ids in OpenStrangle.seen[-1:]}
    assert seen == ("C1",)


@pytest.mark.integration
def test_a_combos_margin_is_that_of_its_legs(tmp_path: Path, ladder: Path) -> None:
    OpenStrangle.clear()

    run(tmp_path, ladder, "combo_strategies:OpenStrangle")

    [(margin, held)] = OpenStrangle.margins
    assert margin > 0
    assert margin == held
