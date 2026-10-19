from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.execution import FeeModel, MakerTakerFeeModel
from nautilus_trader.model import InstrumentClass, OmsType

from sbt2.core.config import ConfigFolder
from sbt2.core.spec import (
    InvalidModelConfigError,
    InvalidVenueProfileError,
    MissingConfigError,
    UnknownModelKindError,
    UnknownVenueProfileError,
    delete_venue_profile,
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
def test_deribit_option_builds_a_nautilus_venue(tmp_path: Path) -> None:
    spec = tmp_path / "spec.toml"
    spec.write_text(OPTION_SPEC)

    [resolved] = load(spec, CONFIG / "venues.toml")
    [venue] = resolved.run_config("/catalog").venues

    assert venue.name == "DERIBIT"
    assert venue.oms_type == OmsType.NETTING
    assert venue.liquidation_enabled is False
    assert isinstance(venue.fee_model, FeeModel)


OPTION_PARAMS = 'params = { bar = "1-HOUR-MID" }'
OPTION_SPEC = (
    SPEC.replace("BTCUSDT-LINEAR.BYBIT", "BTC-30JAN26-100000-C.DERIBIT")
    .replace("bybit_linear", "deribit_option")
    .replace("10000 USDT", "1 BTC")
    .replace("spec_strategies:MinuteLookback", "spec_strategies:DeclaredBar")
    + OPTION_PARAMS
)
DERIBIT_PROFILE = (CONFIG / "venues.toml").read_text().split("[deribit_option]")[1]


def option_venue(tmp_path: Path, extra: str) -> dict[str, Any]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(OPTION_SPEC)
    venues.write_text(f"[deribit_option]{DERIBIT_PROFILE}\n{extra}\n")
    [resolved] = load(spec, venues)
    return dict(resolved.venue)


@pytest.mark.unit
def test_a_deribit_option_profile_reads_its_quote_settings(tmp_path: Path) -> None:
    venue = option_venue(
        tmp_path, "quotes = { interval_seconds = 300, ticks = 2, fraction = 0.1 }"
    )

    assert venue["quotes"] == {"interval_seconds": 300, "ticks": 2, "fraction": 0.1}


@pytest.mark.unit
def test_a_deribit_option_profile_without_quote_settings_uses_the_defaults(
    tmp_path: Path,
) -> None:
    venue = option_venue(tmp_path, "")

    assert venue["quotes"] == {"interval_seconds": 60, "ticks": 1, "fraction": 0.05}


@pytest.mark.unit
def test_a_partial_quote_table_keeps_the_defaults_of_the_rest(tmp_path: Path) -> None:
    venue = option_venue(tmp_path, "quotes = { ticks = 3 }")

    assert venue["quotes"] == {"interval_seconds": 60, "ticks": 3, "fraction": 0.05}


@pytest.mark.unit
def test_a_deribit_option_profile_reads_its_delivery_fee_rates(tmp_path: Path) -> None:
    venue = option_venue(
        tmp_path, 'delivery_fee = { rate = "0.0002", cap_rate = "0.1" }'
    )

    assert venue["delivery_fee"] == {"rate": "0.0002", "cap_rate": "0.1"}


@pytest.mark.unit
def test_a_deribit_option_profile_without_delivery_fee_rates_uses_the_defaults(
    tmp_path: Path,
) -> None:
    venue = option_venue(tmp_path, "")

    assert venue["delivery_fee"] == {"rate": "0.00015", "cap_rate": "0.125"}


@pytest.mark.unit
def test_a_partial_delivery_fee_table_keeps_the_defaults_of_the_rest(
    tmp_path: Path,
) -> None:
    venue = option_venue(tmp_path, "delivery_fee = { rate = 0.0002 }")

    assert venue["delivery_fee"] == {"rate": "0.0002", "cap_rate": "0.125"}


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
        ({"name": None}, InvalidVenueProfileError),
        ({"asset_class": "NOPE"}, InvalidVenueProfileError),
    ],
    ids=["unknown-kind", "bad-config", "no-source", "no-venue", "unknown-asset-class"],
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


@pytest.mark.unit
def test_delete_venue_profile_removes_only_that_profile(tmp_path: Path) -> None:
    venues = tmp_path / "venues.toml"
    put_venue_profile(venues, "p", PROFILE)
    put_venue_profile(venues, "q", PROFILE)

    delete_venue_profile(venues, "p")

    assert venue_profiles(venues) == {"q": PROFILE}


@pytest.mark.unit
def test_deleting_an_unknown_venue_profile_raises_unknown_venue_profile_error(
    tmp_path: Path,
) -> None:
    venues = tmp_path / "venues.toml"
    put_venue_profile(venues, "q", PROFILE)

    with pytest.raises(UnknownVenueProfileError, match="no venue profile p"):
        delete_venue_profile(venues, "p")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("instrument_class", "quotes"),
    [
        ("OPTION", {"spread": 1}),
        ("OPTION", {"interval_seconds": 0}),
        ("OPTION", {"fraction": -0.1}),
        ("SWAP", {"ticks": 1}),
    ],
)
def test_an_invalid_quote_setting_is_rejected(
    tmp_path: Path, instrument_class: str, quotes: dict[str, Any]
) -> None:
    venues = ConfigFolder(tmp_path / "config").venues
    profile = {**PROFILE, "instrument_class": instrument_class, "quotes": quotes}

    with pytest.raises(InvalidVenueProfileError, match="quotes"):
        put_venue_profile(venues, "p", profile)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("instrument_class", "delivery_fee"),
    [
        ("OPTION", {"charge": "1"}),
        ("OPTION", {"rate": "-0.1"}),
        ("OPTION", {"cap_rate": "abc"}),
        ("SWAP", {"rate": "0.1"}),
    ],
)
def test_an_invalid_delivery_fee_setting_is_rejected(
    tmp_path: Path, instrument_class: str, delivery_fee: dict[str, Any]
) -> None:
    venues = ConfigFolder(tmp_path / "config").venues
    profile = {
        **PROFILE,
        "instrument_class": instrument_class,
        "delivery_fee": delivery_fee,
    }

    with pytest.raises(InvalidVenueProfileError, match="delivery_fee"):
        put_venue_profile(venues, "p", profile)


@pytest.mark.unit
def test_a_deribit_option_profile_reads_its_margin_rates(tmp_path: Path) -> None:
    venue = option_venue(
        tmp_path,
        'margin = { base_rate = "0.2", floor_rate = "0.12", maintenance_rate = "0.08" }',
    )

    assert venue["margin"] == {
        "base_rate": "0.2",
        "floor_rate": "0.12",
        "maintenance_rate": "0.08",
    }


@pytest.mark.unit
def test_a_deribit_option_profile_without_margin_rates_uses_the_defaults(
    tmp_path: Path,
) -> None:
    venue = option_venue(tmp_path, "")

    assert venue["margin"] == {
        "base_rate": "0.15",
        "floor_rate": "0.1",
        "maintenance_rate": "0.075",
    }


@pytest.mark.unit
def test_a_partial_margin_table_keeps_the_defaults_of_the_rest(tmp_path: Path) -> None:
    venue = option_venue(tmp_path, "margin = { floor_rate = 0.12 }")

    assert venue["margin"] == {
        "base_rate": "0.15",
        "floor_rate": "0.12",
        "maintenance_rate": "0.075",
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("instrument_class", "margin"),
    [
        ("OPTION", {"charge": "1"}),
        ("OPTION", {"base_rate": "-0.1"}),
        ("OPTION", {"floor_rate": "abc"}),
        ("SWAP", {"base_rate": "0.1"}),
    ],
)
def test_an_invalid_margin_setting_is_rejected(
    tmp_path: Path, instrument_class: str, margin: dict[str, Any]
) -> None:
    venues = ConfigFolder(tmp_path / "config").venues
    profile = {**PROFILE, "instrument_class": instrument_class, "margin": margin}

    with pytest.raises(InvalidVenueProfileError, match="margin"):
        put_venue_profile(venues, "p", profile)


PERPETUAL_SPEC = (
    SPEC.replace("BTCUSDT-LINEAR.BYBIT", "BTC-PERPETUAL.DERIBIT")
    .replace("bybit_linear", "deribit_perpetual")
    .replace("10000 USDT", "1 BTC")
    .replace("spec_strategies:MinuteLookback", "run_strategies:BuyThenSell")
)


@pytest.mark.unit
def test_deribit_perpetual_builds_a_nautilus_venue(tmp_path: Path) -> None:
    spec = tmp_path / "spec.toml"
    spec.write_text(PERPETUAL_SPEC)

    [resolved] = load(spec, CONFIG / "venues.toml")
    [venue] = resolved.run_config("/catalog").venues

    assert venue.name == "DERIBIT"
    assert venue.oms_type == OmsType.NETTING
    assert venue.liquidation_enabled is False
    assert isinstance(venue.fee_model, MakerTakerFeeModel)
    assert resolved.venue["fee_model"]["config"] == {
        "maker_rate": "0",
        "taker_rate": "0.0005",
    }
