from pathlib import Path

import pytest
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import OmsType

from sbt2.core.spec import MissingConfigError, load, venue_profiles

CONFIG = Path(__file__).parents[1] / "config"
SPEC = """
strategy = "spec_strategies:MinuteLookback"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
period = [2024-01-01, 2024-03-01]
split = { validation_start = 2024-02-01, test_start = 2024-02-15 }
part = "train"
venue = "bybit_linear"
capital = "10000 USDT"
"""


@pytest.mark.unit
def test_bybit_linear_builds_a_nautilus_venue(tmp_path: Path) -> None:
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC)

    [resolved] = load(spec, CONFIG / "venues.toml")
    [venue] = resolved.run_config("/catalog").venues

    assert venue.name == "BYBIT"
    assert venue.oms_type == OmsType.NETTING
    assert venue.liquidation_enabled is False
    assert isinstance(venue.fee_model, MakerTakerFeeModel)


@pytest.mark.unit
def test_a_missing_venue_profiles_file_names_it(tmp_path: Path) -> None:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)

    with pytest.raises(MissingConfigError, match=str(venues)):
        load(spec, venues)


TWO_PROFILES = """
[linear]
name = "BYBIT"
source = "bybit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
fee_model = { kind = "fixed", config = { commission = "1 USDT" } }

[leveraged]
name = "BYBIT"
source = "bybit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
default_leverage = 3
"""


@pytest.mark.unit
def test_venue_profiles_list_every_profile_as_stored(tmp_path: Path) -> None:
    venues = tmp_path / "venues.toml"
    venues.write_text(TWO_PROFILES)

    assert venue_profiles(venues) == {
        "linear": {
            "name": "BYBIT",
            "source": "bybit",
            "asset_class": "CRYPTOCURRENCY",
            "instrument_class": "SWAP",
            "fee_model": {"kind": "fixed", "config": {"commission": "1 USDT"}},
        },
        "leveraged": {
            "name": "BYBIT",
            "source": "bybit",
            "asset_class": "CRYPTOCURRENCY",
            "instrument_class": "SWAP",
            "default_leverage": 3,
        },
    }


@pytest.mark.unit
def test_venue_profiles_of_a_missing_file_are_empty(tmp_path: Path) -> None:
    assert venue_profiles(tmp_path / "venues.toml") == {}
