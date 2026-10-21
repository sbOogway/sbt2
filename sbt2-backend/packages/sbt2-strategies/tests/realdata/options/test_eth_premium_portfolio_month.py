"""A month of BTC and ETH options; run with ``pytest -m realdata``."""

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from month_kit import run_month

from sbt2.core.market import Rates
from sbt2.core.results import ParquetResultStore


def books_by_underlying(store: ParquetResultStore, run_id: str) -> dict[str, set[int]]:
    fills = store.load(run_id, "fills")
    orders = store.load(run_id, "orders").set_index("venue_order_id")["tags"]
    tagged = fills.assign(
        combo=[next(iter(orders[each])) for each in fills["venue_order_id"]],
        underlying=fills["instrument_id"].str.split("-").str[0],
    )
    counts = tagged.groupby(["underlying", "combo"])["instrument_id"].nunique()
    return {str(coin): set(rows) for coin, rows in counts.groupby(level=0)}


@pytest.mark.realdata
@pytest.mark.e2e
def test_the_portfolio_runs_on_a_month_of_btc_and_eth_options(tmp_path: Path) -> None:
    store, run_id = run_month("options/eth_premium_portfolio_month.toml", tmp_path)

    books = books_by_underlying(store, run_id)
    assert set(books) == {"BTC", "ETH"}
    assert all(counts >= {2, 4} for counts in books.values())
    trades = store.load(run_id, "trades")
    assert set(trades["currency"]) == {"BTC", "ETH"}
    equity = store.load(run_id, "equity")
    last = equity["ts_event"].iloc[-1]
    assert last >= datetime(2025, 1, 31, tzinfo=UTC)
    rates = Rates.from_table("BTC", store.load(run_id, "rates"))
    balances = store.load(run_id, "balances")
    at_end = balances.loc[balances["ts_event"] == last].groupby("currency").last()
    times = pd.DatetimeIndex(at_end["ts_event"])
    converted = at_end["total_equity"] * rates.factors(list(at_end.index), times)
    assert converted.sum() == pytest.approx(float(equity["total_equity"].iloc[-1]))
