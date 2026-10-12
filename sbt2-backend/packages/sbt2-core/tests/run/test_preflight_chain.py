from pathlib import Path

import pytest
from chain_source import (
    DAYS,
    DELIVERY,
    INDEX_PRICE,
    ChainSource,
    ChainSourceWithoutTrades,
)
from nautilus_trader.model import IndexPriceUpdate, InstrumentId, MarkPriceUpdate

from sbt2.core.run import DataFolders, MissingDataError, preflight
from sbt2.core.spec import ResolvedRunSpec, load
from sbt2.data import Catalog, Window

SPEC = """
strategy = "run_strategies:ActOnSchedule"
instruments = ["BTC-OPTIONS.DERIBIT"]
period = [2024-01-01, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
venue = "deribit_option"
capital = "1 BTC"
"""
VENUES = """
[deribit_option]
name = "DERIBIT"
source = "deribit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "OPTION"
fee_model = { kind = "capped_option", config = { maker_rate = "0.0003", taker_rate = "0.0003", cap_rate = "0.125" } }
"""
INDEX = InstrumentId.from_str("BTC_USD.DERIBIT")
DVOL = InstrumentId.from_str("BTC_DVOL.DERIBIT")
DELIVERY_ID = InstrumentId.from_str("BTC_USD_DELIVERY.DERIBIT")
IN_BAND = InstrumentId.from_str("BTC-2JAN24-45000-C.DERIBIT")


def spec_of(tmp_path: Path) -> ResolvedRunSpec:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    return resolved


def folders_of(tmp_path: Path) -> DataFolders:
    return DataFolders(tmp_path / "raw", tmp_path / "catalog")


def frame_of(
    folders: DataFolders, instrument_id: InstrumentId, data_type: type
) -> list[float]:
    window = Window.of_days(DAYS[0], DAYS[-1])
    frame = Catalog(folders.catalog).frame(instrument_id, data_type, window)
    return list(frame["price"])


@pytest.mark.integration
def test_preflight_fetches_the_index_dvol_and_delivery_prices_of_a_chain_run(
    tmp_path: Path,
) -> None:
    folders = folders_of(tmp_path)
    source = ChainSource()

    preflight(spec_of(tmp_path), source, folders)

    [delivery] = [each for each in source.asked if "DELIVERY" in each.name]
    assert delivery.name.endswith("2024-01-02.json")
    assert set(frame_of(folders, INDEX, IndexPriceUpdate)) == {INDEX_PRICE}
    assert len(frame_of(folders, DVOL, IndexPriceUpdate)) == 48
    assert frame_of(folders, DELIVERY_ID, IndexPriceUpdate) == [DELIVERY]
    assert frame_of(folders, IN_BAND, MarkPriceUpdate)


@pytest.mark.integration
def test_a_chain_run_without_its_index_names_the_missing_days(
    tmp_path: Path,
) -> None:
    days = ".*".join(f"BTC-OPTIONS.DERIBIT IndexPriceUpdate {each}" for each in DAYS)

    with pytest.raises(MissingDataError, match=days):
        preflight(spec_of(tmp_path), ChainSourceWithoutTrades(), folders_of(tmp_path))


@pytest.mark.integration
def test_a_covered_chain_run_fetches_nothing(tmp_path: Path) -> None:
    folders = folders_of(tmp_path)
    preflight(spec_of(tmp_path), ChainSource(), folders)
    again = ChainSource()

    assert preflight(spec_of(tmp_path), again, folders) == ()
    assert again.asked == []
