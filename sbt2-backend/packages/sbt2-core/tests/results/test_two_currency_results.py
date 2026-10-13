from pathlib import Path

import pandas as pd
import pytest
from option_catalog import ETH_PRICE, HOURS, INDEX_PRICE, build_two_chain_catalog
from option_runs import run_two_chains
from two_chain_strategies import OpenBothStrangles

from sbt2.core.results import ParquetResultStore, Segment, full_metrics

PRICES = [ETH_PRICE + 10.0 * hour for hour in range(HOURS)]


@pytest.fixture(scope="module")
def two_currency_run(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[ParquetResultStore, str, Path]:
    catalog = tmp_path_factory.mktemp("rising_eth")
    build_two_chain_catalog(catalog, eth_prices=PRICES)
    OpenBothStrangles.clear()
    store, run_id = run_two_chains(
        tmp_path_factory.mktemp("two_currencies"),
        catalog,
        "two_chain_strategies:TradeBothStrangles",
    )
    return store, run_id, catalog


def reported_pnls(store: ParquetResultStore, run_id: str) -> list[float]:
    """The realized PnL of each closed position, in BTC at the time of its close."""
    positions = store.load(run_id, "positions")
    start = pd.Timestamp("2024-01-01", tz="UTC")
    found = []
    for text, closed in zip(
        positions["realized_pnl"], positions["ts_closed"], strict=True
    ):
        amount, code = str(text).split()
        hour = int((pd.Timestamp(closed) - start).total_seconds() // 3600)
        rate = 1.0 if code == "BTC" else PRICES[min(hour, HOURS - 1)] / INDEX_PRICE
        found.append(float(amount) * rate)
    return found


@pytest.mark.integration
def test_a_stored_two_currency_run_has_full_metrics(
    two_currency_run: tuple[ParquetResultStore, str, Path],
) -> None:
    store, run_id, _ = two_currency_run
    stored = store.stored_run(run_id)

    found = full_metrics(stored.tables, Segment.of_run(stored.spec))

    pnls = reported_pnls(store, run_id)
    losers = [each for each in pnls if each < 0]
    assert found.pnls["Avg Loser"] == pytest.approx(sum(losers) / len(losers))
    assert len(found.pnls_by_instrument) == 4


@pytest.mark.integration
def test_a_two_currency_run_stores_the_rates_it_converted_with(
    two_currency_run: tuple[ParquetResultStore, str, Path],
) -> None:
    store, run_id, _ = two_currency_run

    rates = store.load(run_id, "rates")

    assert list(rates.columns) == ["ts_event", "currency", "rate"]
    assert set(rates["currency"]) == {"ETH"}
    grid = set(store.load(run_id, "balances")["ts_event"])
    assert set(rates["ts_event"]) == grid
    start = pd.Timestamp("2024-01-01", tz="UTC")
    for moment, rate in zip(rates["ts_event"], rates["rate"], strict=True):
        hour = int((pd.Timestamp(moment) - start).total_seconds() // 3600)
        assert rate == pytest.approx(PRICES[min(hour, HOURS - 1)] / INDEX_PRICE)
