"""A month of BTC on five exchanges' perpetuals; run with ``pytest -m realdata``."""

import math
from pathlib import Path

import pytest
from month_kit import run_month

SPECS = [
    "vwap/vwap_trend_month.toml",
    "vwap/vwap_band_fade_month.toml",
    "vwap/vwap_momentum_month.toml",
]


@pytest.mark.realdata
@pytest.mark.integration
@pytest.mark.parametrize("spec", SPECS)
def test_each_vwap_strategy_runs_a_real_month_of_btc_with_five_feeds(
    spec: str, tmp_path: Path
) -> None:
    store, run_id = run_month(spec, tmp_path)

    assert len(store.load(run_id, "trades")) > 0
    equity = store.load(run_id, "equity")
    assert math.isfinite(float(equity["total_equity"].iloc[-1]))
