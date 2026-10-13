from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from combo_strategies import LADDER_EXPIRY
from nautilus_trader.model import black_scholes_greeks
from option_catalog import (
    ETH_INDEX_ID,
    ETH_PRICE,
    HOURS,
    INDEX_ID,
    INDEX_PRICE,
    MARK_IV,
    START,
    build_two_chain_catalog,
    write_index_history,
)
from option_runs import run_two_chains
from two_chain_strategies import MeasureMargins, OpenBothStrangles

from sbt2.core.results import trade_statistics

BTC_MOVES = [0.02, -0.01, 0.03, -0.02, 0.01, 0.015, -0.025, 0.02, -0.005, 0.01]
ETH_BETA = 1.5


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
def test_the_bpr_of_a_two_currency_run_is_in_the_reporting_currency(
    tmp_path: Path,
) -> None:
    MeasureMargins.margins.clear()
    prices = [ETH_PRICE + 10.0 * hour for hour in range(HOURS)]
    path = tmp_path / "rising_eth"
    build_two_chain_catalog(path, eth_prices=prices)

    store, run_id = run_two_chains(
        tmp_path, path, "two_chain_strategies:MeasureMargins"
    )

    rows = store.load(run_id, "margin")
    assert set(rows["currency"]) == {"BTC"}
    margin = rows.groupby("ts_event")["margin_used"].last()
    held = {
        tick: coins
        for tick, coins in MeasureMargins.margins.items()
        if set(coins) == {"BTC", "ETH"} and tick in margin.index
    }
    assert len(held) > 30
    for tick, coins in held.items():
        hour = int((tick - START).total_seconds() // 3600)
        rate = prices[min(hour, HOURS - 1)] / INDEX_PRICE
        expected = float(coins["BTC"]) + float(coins["ETH"]) * rate
        assert margin.loc[tick] == pytest.approx(expected)


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


def closes(moves: list[float], last: float) -> list[float]:
    """Prices that rise by ``moves`` and end at ``last``."""
    prices = [1.0]
    for move in moves:
        prices.append(prices[-1] * (1 + move))
    return [price * last / prices[-1] for price in prices]


def strangle_greeks(
    index: float, strikes: tuple[int, int], hour: datetime
) -> tuple[float, float]:
    """The theta (USD per day) and the delta of the short strangle at ``hour``."""
    years = (LADDER_EXPIRY - hour) / timedelta(days=365)
    theta = delta = 0.0
    for strike, is_call in zip(strikes, (False, True), strict=True):
        found = black_scholes_greeks(
            index, 0.0, 0.0, MARK_IV, is_call, float(strike), years
        )
        theta -= found.theta
        delta -= found.delta
    return theta, delta


@pytest.mark.integration
def test_the_portfolio_greeks_of_a_two_currency_run_weight_eth_by_its_beta(
    tmp_path: Path,
) -> None:
    OpenBothStrangles.clear()
    path = tmp_path / "with_history"
    build_two_chain_catalog(path)
    btc_closes = closes(BTC_MOVES, INDEX_PRICE)
    eth_closes = closes([ETH_BETA * each for each in BTC_MOVES], ETH_PRICE)
    midnights = [24 * day for day in range(-10, 0)]
    before_start = {INDEX_ID: btc_closes[:-1], ETH_INDEX_ID: eth_closes[:-1]}
    for series, prices in before_start.items():
        write_index_history(path, dict(zip(midnights, prices, strict=True)), series)

    store, run_id = run_two_chains(
        tmp_path, path, "two_chain_strategies:OpenBothWithHistory"
    )

    rows = store.load(run_id, "portfolio_greeks")
    first_day = rows.loc[
        (rows["beta_weighted_delta"] != 0)
        & (rows["ts_event"] < datetime(2024, 1, 2, tzinfo=UTC))
    ]
    assert len(first_day) > 15
    [_, both] = OpenBothStrangles.balances
    equity = float(both["BTC"]) + float(both["ETH"]) * ETH_PRICE / INDEX_PRICE
    for row in first_day.itertuples():
        hour = row.ts_event.to_pydatetime()
        btc_theta, btc_delta = strangle_greeks(INDEX_PRICE, (40000, 50000), hour)
        eth_theta, eth_delta = strangle_greeks(ETH_PRICE, (2000, 3000), hour)
        theta = (btc_theta + eth_theta) / INDEX_PRICE
        delta = btc_delta + ETH_BETA * ETH_PRICE / INDEX_PRICE * eth_delta
        assert row.theta == pytest.approx(theta)
        assert row.beta_weighted_delta == pytest.approx(delta)
        assert row.theta_ratio == pytest.approx(theta / equity)
