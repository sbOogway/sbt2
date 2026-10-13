from pathlib import Path

import pandas as pd
import pytest
from option_catalog import build_ladder_catalog
from option_runs import run_options


@pytest.fixture(scope="module")
def ladder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("ladder_catalog")
    build_ladder_catalog(path)
    return path


@pytest.mark.integration
def test_a_single_currency_run_keeps_its_tables(tmp_path: Path, ladder: Path) -> None:
    store, run_id = run_options(tmp_path, ladder, "combo_strategies:TwoTrades")

    equity = store.load(run_id, "equity")
    balances = store.load(run_id, "balances")
    trades = store.load(run_id, "trades")
    assert list(equity.columns) == [
        "ts_event",
        "account_id",
        "currency",
        "total_equity",
    ]
    assert set(equity["currency"]) == {"BTC"}
    pd.testing.assert_frame_equal(balances, equity)
    assert len(trades) == 2
    assert set(trades["currency"]) == {"BTC"}
    assert list(trades["pl_report"]) == list(trades["pl"])
