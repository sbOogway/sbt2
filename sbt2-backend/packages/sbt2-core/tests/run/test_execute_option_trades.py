from decimal import Decimal
from pathlib import Path

import pytest
from combo_strategies import OpenStrangle
from option_catalog import INDEX_PRICE, build_ladder_catalog
from option_runs import run_options

from sbt2.core.results import trade_statistics


@pytest.fixture(scope="module")
def ladder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("ladder_catalog")
    build_ladder_catalog(path, mark_step=Decimal("-0.001"))
    return path


@pytest.mark.integration
def test_an_option_run_stores_its_trades_and_their_statistics(
    tmp_path: Path, ladder: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(tmp_path, ladder, "combo_strategies:TwoTrades")

    trades = store.load(run_id, "trades").set_index("trade_id")
    assert list(trades.index) == ["C1", "C2"]
    assert trades.loc["C1", "ts_closed"] > trades.loc["C2", "ts_closed"]
    assert list(trades["index_at_close"]) == [INDEX_PRICE, INDEX_PRICE]
    assert list(trades["pl_usd"]) == pytest.approx(list(trades["pl"] * INDEX_PRICE))
    equity = store.load(run_id, "equity")
    assert trades["pl"].sum() == pytest.approx(
        equity["total_equity"].iloc[-1] - 1.0, abs=1e-6
    )
    run = store.stored_run(run_id).tables
    found = trade_statistics(run.trades, run.margin, run.currency)
    assert found["Occurrences"] == 2
    assert (found["BPR Peak"] or 0.0) > 0
