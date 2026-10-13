from pathlib import Path

import pytest
from option_catalog import START, build_two_chain_catalog
from option_runs import run_two_chains
from two_chain_strategies import OpenBothStrangles


@pytest.mark.integration
def test_combo_exit_uses_each_combos_chain(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    build_two_chain_catalog(catalog)
    OpenBothStrangles.clear()

    store, run_id = run_two_chains(
        tmp_path, catalog, "two_chain_strategies:ExitBothStrangles"
    )

    trades = store.load(run_id, "trades")
    assert len(trades) == 2
    assert set(trades["currency"]) == {"BTC", "ETH"}
    assert store.load(run_id, "equity")["ts_event"].max().date() > START.date()
