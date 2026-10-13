from decimal import Decimal
from pathlib import Path

import pytest
from option_catalog import HOURS, build_two_chain_catalog
from option_runs import run_two_chains
from two_chain_strategies import ReadEquity


@pytest.mark.integration
def test_equity_converts_every_balance_into_the_asked_coin(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    build_two_chain_catalog(catalog, [3000.0] * HOURS, [60000.0] * HOURS)
    ReadEquity.seen.clear()

    run_two_chains(tmp_path, catalog, "two_chain_strategies:ReadEquity")

    assert ReadEquity.seen
    assert all(
        sample == {"BTC": Decimal(2), "ETH": Decimal(40)} for sample in ReadEquity.seen
    )
