"""A month of real Deribit BTC options; run with ``pytest -m realdata``."""

from pathlib import Path

import pytest
from month_kit import COIN_PRECISION, equity_after_last_trade, run_month


@pytest.mark.realdata
@pytest.mark.e2e
def test_a_short_strangle_runs_on_a_month_of_deribit_btc_options(
    tmp_path: Path,
) -> None:
    store, run_id = run_month("options/short_strangle_month.toml", tmp_path)

    trades = store.load(run_id, "trades")
    assert len(trades) >= 1
    equity = store.load(run_id, "equity")
    gained = equity_after_last_trade(equity, trades) - 1.0
    assert trades["pl"].sum() == pytest.approx(gained, abs=COIN_PRECISION)
