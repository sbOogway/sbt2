from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from option_catalog import (
    ETH_PRICE,
    HOURS,
    INDEX_PRICE,
    START,
    build_two_chain_catalog,
)
from option_runs import run_two_chains
from two_chain_strategies import OpenBothStrangles

from sbt2.core.results import trade_statistics


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("two_chain_catalog")
    build_two_chain_catalog(path)
    return path


def latest_balance(balances: pd.DataFrame, currency: str) -> pd.Series:
    """The balance of ``currency`` at each time, the last of the rows of a time."""
    rows = balances.loc[balances["currency"] == currency]
    return rows.groupby("ts_event")["total_equity"].last()


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
def test_the_equity_of_a_two_currency_run_is_the_converted_total(
    tmp_path: Path,
) -> None:
    OpenBothStrangles.clear()
    prices = [ETH_PRICE + 10.0 * hour for hour in range(HOURS)]
    path = tmp_path / "rising_eth"
    build_two_chain_catalog(path, eth_prices=prices)

    store, run_id = run_two_chains(
        tmp_path, path, "two_chain_strategies:OpenBothStrangles"
    )

    equity = store.load(run_id, "equity")
    balances = store.load(run_id, "balances")
    assert set(equity["currency"]) == {"BTC"}
    assert set(balances["currency"]) == {"BTC", "ETH"}
    btc, eth = (latest_balance(balances, each) for each in ("BTC", "ETH"))
    assert btc.iloc[0] == pytest.approx(1.0)
    assert eth.iloc[0] == pytest.approx(20.0)
    assert eth.iloc[-1] != pytest.approx(20.0, abs=0.01)
    since = [pd.Timestamp(each).to_pydatetime() - START for each in btc.index]
    hours = [int(each.total_seconds() // 3600) for each in since]
    rates = [prices[min(hour, HOURS - 1)] / INDEX_PRICE for hour in hours]
    expected = btc.to_numpy() + eth.to_numpy() * rates
    assert list(equity["ts_event"]) == list(btc.index)
    assert list(equity["total_equity"]) == pytest.approx(list(expected))


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
