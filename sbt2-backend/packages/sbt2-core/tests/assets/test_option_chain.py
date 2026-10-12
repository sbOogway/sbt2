from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model import AssetClass, InstrumentClass, InstrumentId
from option_catalog import CHAIN_ID, HOURS, build_chain_catalog, chain_contract_id

from sbt2.core.assets import ChainJob, asset_profile
from sbt2.data import Catalog

WINDOW = (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 3, tzinfo=UTC))
EVERYTHING = {"max_dte": 365, "strike_band": "5"}
PROFILE = asset_profile(AssetClass.CRYPTOCURRENCY, InstrumentClass.OPTION)


def ids(label: str, *strikes: int) -> set[InstrumentId]:
    return {chain_contract_id(label, each, kind) for each in strikes for kind in "CP"}


def chosen(catalog: Path, table: dict[str, Any]) -> set[InstrumentId]:
    complete = PROFILE.chain.complete(table)
    job = ChainJob(Catalog(catalog), CHAIN_ID, WINDOW, complete)
    return set(PROFILE.chain.contracts(job))


@pytest.fixture(scope="module")
def flat(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("flat_chain")
    build_chain_catalog(path)
    return path


@pytest.fixture(scope="module")
def rising(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("rising_chain")
    build_chain_catalog(path, [45000.0] * (HOURS // 2) + [65000.0] * (HOURS // 2))
    return path


@pytest.mark.unit
def test_the_chain_loads_only_contracts_alive_in_the_window(flat: Path) -> None:
    found = chosen(flat, EVERYTHING)

    assert found == (
        ids("2JAN24", 40000, 45000, 50000)
        | ids("12JAN24", 45000, 90000)
        | ids("15FEB24", 45000)
        | ids("28JUN24", 45000)
    )
    assert not found & ids("31DEC23", 45000)


@pytest.mark.unit
def test_the_chain_loads_only_contracts_inside_the_dte_band(flat: Path) -> None:
    far = chosen(flat, {**EVERYTHING, "min_dte": 30, "max_dte": 60})
    near = chosen(flat, {**EVERYTHING, "max_dte": 5})
    middle = chosen(flat, {**EVERYTHING, "min_dte": 10, "max_dte": 12})

    assert far == ids("15FEB24", 45000)
    assert near == ids("2JAN24", 40000, 45000, 50000)
    assert middle == ids("12JAN24", 45000, 90000)


@pytest.mark.unit
def test_the_chain_loads_only_contracts_inside_the_strike_band_of_the_index(
    flat: Path, rising: Path
) -> None:
    wide = chosen(flat, {})
    narrow = chosen(flat, {"strike_band": "0.05"})
    after_the_rise = chosen(rising, {})

    assert ids("12JAN24", 90000) & wide == set()
    assert narrow == ids("2JAN24", 45000) | ids("12JAN24", 45000) | ids(
        "15FEB24", 45000
    )
    assert ids("12JAN24", 90000) <= after_the_rise
