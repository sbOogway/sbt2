"""A month of real Deribit BTC options; run with ``pytest -m realdata``."""

from pathlib import Path

import pytest
from month_kit import run_month

from sbt2.core.results import ParquetResultStore

STRANGLE_LEGS, CONDOR_LEGS = 2, 4
# combos still open at the end hold unrealised P/L and the fees of their entry
OPEN_COMBOS = 0.002


def legs_per_combo(store: ParquetResultStore, run_id: str) -> set[int]:
    """How many contracts each combo of the run traded."""
    fills = store.load(run_id, "fills")
    orders = store.load(run_id, "orders").set_index("venue_order_id")["tags"]
    combos = [next(iter(orders[each])) for each in fills["venue_order_id"]]
    return set(fills.groupby(combos)["instrument_id"].nunique())


@pytest.mark.realdata
@pytest.mark.e2e
def test_the_portfolio_runs_on_a_month_of_deribit_btc_options(tmp_path: Path) -> None:
    store, run_id = run_month("options/premium_portfolio_month.toml", tmp_path)

    assert legs_per_combo(store, run_id) >= {STRANGLE_LEGS, CONDOR_LEGS}
    trades = store.load(run_id, "trades")
    equity = store.load(run_id, "equity")
    gained = float(equity["total_equity"].iloc[-1]) - 1.0
    assert trades["pl"].sum() == pytest.approx(gained, abs=OPEN_COMBOS)
