from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import InstrumentClass, OmsType

from sbt2.core.config import ConfigFolder
from sbt2.core.spec import (
    InvalidModelConfigError,
    InvalidVenueProfileError,
    MissingConfigError,
    UnknownModelKindError,
    load,
    put_venue_profile,
    venue_profiles,
)
from sbt2.core.spec.resolve.venues import venue_profile

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


PROFILE = {
    "name": "BYBIT",
    "source": "bybit",
    "asset_class": "CRYPTOCURRENCY",
    "instrument_class": "SWAP",
    "fee_model": {
        "kind": "maker_taker",
        "config": {"maker_rate": "0.0002", "taker_rate": "0.00055"},
    },
}


@pytest.mark.unit
def test_put_venue_profile_writes_a_profile_the_next_read_sees(tmp_path: Path) -> None:
    venues = ConfigFolder(tmp_path / "config").venues

    put_venue_profile(venues, "p", PROFILE)

    profile = venue_profile(venues, "p")
    assert profile.source == "bybit"
    assert profile.asset.instrument_class == InstrumentClass.SWAP
    assert profile.arguments["fee_model"] == PROFILE["fee_model"]


@pytest.mark.unit
def test_put_venue_profile_replaces_the_profile_of_the_same_name(
    tmp_path: Path,
) -> None:
    venues = tmp_path / "venues.toml"
    put_venue_profile(venues, "other", PROFILE)
    put_venue_profile(venues, "p", PROFILE)

    put_venue_profile(venues, "p", {**PROFILE, "default_leverage": 5})

    assert venue_profiles(venues) == {
        "other": PROFILE,
        "p": {**PROFILE, "default_leverage": 5},
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"fee_model": {"kind": "nope"}}, UnknownModelKindError),
        ({"fee_model": {"kind": "fixed", "config": {}}}, InvalidModelConfigError),
        ({"source": None}, InvalidVenueProfileError),
        ({"asset_class": "NOPE"}, InvalidVenueProfileError),
    ],
    ids=["unknown-kind", "bad-config", "no-source", "unknown-asset-class"],
)
def test_invalid_venue_profile_is_rejected_and_leaves_the_file_unchanged(
    tmp_path: Path, change: dict[str, Any], error: type[Exception]
) -> None:
    venues = tmp_path / "venues.toml"
    put_venue_profile(venues, "p", PROFILE)
    before = venues.read_bytes()
    profile = {
        key: value for key, value in {**PROFILE, **change}.items() if value is not None
    }

    with pytest.raises(error):
        put_venue_profile(venues, "p", profile)

    assert venues.read_bytes() == before


@pytest.mark.unit
def test_a_failed_config_write_leaves_the_previous_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    venues = tmp_path / "venues.toml"
    put_venue_profile(venues, "p", PROFILE)
    before = venues.read_bytes()

    def fail(*_args: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        put_venue_profile(venues, "q", PROFILE)

    assert venues.read_bytes() == before
    assert [each.name for each in tmp_path.iterdir()] == ["venues.toml"]
