from decimal import Decimal
from pathlib import Path

import pytest
from option_catalog import ETH_PRICE, INDEX_PRICE, build_two_chain_catalog
from option_runs import run_two_chains
from two_chain_strategies import OpenBothStrangles

from sbt2.core.results import trade_statistics


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("two_chain_catalog")
    build_two_chain_catalog(path)
    return path


@pytest.mark.integration
def test_a_run_trades_btc_and_eth_combos_from_two_capitals(
    tmp_path: Path, catalog: Path
) -> None:
    OpenBothStrangles.clear()

    store, run_id = run_two_chains(
        tmp_path, catalog, "two_chain_strategies:OpenBothStrangles"
    )

    fills = store.load(run_id, "fills")
    assert sorted(fills["instrument_id"]) == [
        "BTC-12JAN24-40000-P.DERIBIT",
        "BTC-12JAN24-50000-C.DERIBIT",
        "ETH-12JAN24-2000-P.DERIBIT",
        "ETH-12JAN24-3000-C.DERIBIT",
    ]
    [btc, eth] = OpenBothStrangles.opened
    assert {each.contract.settlement_currency.code for each in btc.legs} == {"BTC"}
    assert {each.contract.settlement_currency.code for each in eth.legs} == {"ETH"}
    [after_btc, after_eth] = OpenBothStrangles.balances
    assert after_btc["ETH"] == Decimal(20)
    assert after_btc["BTC"] > 1
    assert after_eth["BTC"] == after_btc["BTC"]
    assert after_eth["ETH"] > 20


@pytest.mark.integration
def test_the_trades_of_a_two_currency_run_report_in_one_currency(
    tmp_path: Path, catalog: Path
) -> None:
    OpenBothStrangles.clear()

    store, run_id = run_two_chains(
        tmp_path, catalog, "two_chain_strategies:TradeBothStrangles"
    )

    trades = store.load(run_id, "trades").set_index("trade_id")
    assert list(trades.index) == ["C1", "C2"]
    assert list(trades["currency"]) == ["BTC", "ETH"]
    assert trades.loc["C1", "pl_report"] == pytest.approx(trades.loc["C1", "pl"])
    in_btc = trades.loc["C2", "pl"] * ETH_PRICE / INDEX_PRICE
    assert trades.loc["C2", "pl_report"] == pytest.approx(in_btc)
    assert trades.loc["C2", "pl_usd"] == pytest.approx(
        trades.loc["C2", "pl"] * ETH_PRICE
    )
    run = store.stored_run(run_id).tables
    found = trade_statistics(run.trades, run.margin, run.currency)
    assert found["Occurrences"] == 2
    assert found["Average P/L"] == pytest.approx(trades["pl_report"].mean())
    assert found["Largest Loss"] == pytest.approx(trades["pl_report"].min())
