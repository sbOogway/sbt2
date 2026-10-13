from pathlib import Path

import pytest
from option_catalog import ETH_DVOL_ID, HOURS, build_two_chain_catalog, write_dvol
from option_runs import run_two_chains
from two_chain_strategies import ReadChainRanks, ReadChains, ReadTheChain


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("two_chain_catalog")
    build_two_chain_catalog(path)
    return path


@pytest.mark.integration
def test_chains_maps_each_underlying_to_its_chain(
    tmp_path: Path, catalog: Path
) -> None:
    ReadChains.seen.clear()

    run_two_chains(tmp_path, catalog, "two_chain_strategies:ReadChains")

    assert len(ReadChains.seen) > 40
    for chains in ReadChains.seen.values():
        assert chains == {"BTC": {"BTC"}, "ETH": {"ETH"}}


@pytest.mark.integration
def test_chain_fails_with_a_reason_when_the_run_has_several(
    tmp_path: Path, catalog: Path
) -> None:
    ReadTheChain.errors.clear()

    run_two_chains(tmp_path, catalog, "two_chain_strategies:ReadTheChain")

    assert len(ReadTheChain.errors) > 40
    assert all("chains" in each for each in ReadTheChain.errors)
    assert all("BTC" in each and "ETH" in each for each in ReadTheChain.errors)


@pytest.mark.integration
def test_each_chain_ranks_iv_on_its_own_volatility_index(tmp_path: Path) -> None:
    ReadChainRanks.ranks.clear()
    path = tmp_path / "with_dvol"
    build_two_chain_catalog(path)
    write_dvol(path, {hour: 50.0 + hour for hour in range(HOURS)})
    write_dvol(path, {hour: 100.0 - hour for hour in range(HOURS)}, ETH_DVOL_ID)

    run_two_chains(tmp_path, path, "two_chain_strategies:ReadChainRanks")

    ranks = ReadChainRanks.ranks
    assert len(ranks) > 40
    assert {each["BTC"] for each in ranks.values()} == {1.0}
    assert {each["ETH"] for each in ranks.values()} == {0.0}
