from pathlib import Path

import numpy as np
import pytest
from option_catalog import (
    ETH_INDEX_ID,
    INDEX_ID,
    build_two_chain_catalog,
    write_index_history,
)
from option_runs import run_two_chains
from two_chain_strategies import ReadIndexCorrelation


@pytest.mark.integration
def test_index_correlation_comes_from_daily_index_returns(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    build_two_chain_catalog(catalog)
    btc = [40000, 42000, 41000, 43000, 44000, 42000, 45000]
    eth = [2200, 2300, 2250, 2400, 2350, 2450, 2500]
    for series, prices in ((INDEX_ID, btc), (ETH_INDEX_ID, eth)):
        write_index_history(
            catalog, {24 * (i - 7): price for i, price in enumerate(prices)}, series
        )
    ReadIndexCorrelation.seen.clear()

    run_two_chains(tmp_path, catalog, "two_chain_strategies:ReadIndexCorrelation")

    first = next(iter(ReadIndexCorrelation.seen.values()))
    btc.append(45000)
    eth.append(2500)
    expected = np.corrcoef(np.diff(btc) / btc[:-1], np.diff(eth) / eth[:-1])[0, 1]
    assert first["BTC"]["ETH"] == pytest.approx(expected)
    assert first["ETH"]["BTC"] == pytest.approx(expected)
    assert first["BTC"]["BTC"] == first["ETH"]["ETH"] == 1.0


@pytest.mark.integration
def test_index_correlation_is_one_without_enough_history(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    build_two_chain_catalog(catalog)
    ReadIndexCorrelation.seen.clear()

    run_two_chains(tmp_path, catalog, "two_chain_strategies:ReadIndexCorrelation")

    assert ReadIndexCorrelation.seen
    assert all(
        matrix == {"BTC": {"BTC": 1.0, "ETH": 1.0}, "ETH": {"BTC": 1.0, "ETH": 1.0}}
        for matrix in ReadIndexCorrelation.seen.values()
    )
