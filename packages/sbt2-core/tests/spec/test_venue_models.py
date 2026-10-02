import json
from pathlib import Path

import pytest
from nautilus_trader.execution import (
    DefaultFillModel,
    FixedFeeModel,
    MakerTakerFeeModel,
)

from sbt2.core.spec import (
    InvalidModelConfigError,
    InvalidVenueProfileError,
    OutdatedRunError,
    ResolvedRunSpec,
    UnknownModelKindError,
    load,
)

SPEC = """
strategy = "spec_strategies:MinuteLookback"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
period = [2024-01-01, 2024-03-01]
split = { validation_start = 2024-02-01, test_start = 2024-02-15 }
part = "train"
venue = "modelled"
capital = "10000 USDT"
"""
PROFILE = """
[modelled]
name = "BYBIT"
source = "bybit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
"""
CONFIGS = {
    "maker_taker": '{ maker_rate = "0.0002", taker_rate = "0.00055" }',
    "fixed": '{ commission = "1 USDT" }',
    "default": "{ prob_fill_on_limit = 0.5 }",
}


@pytest.fixture
def paths(tmp_path: Path) -> tuple[Path, Path]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)
    venues.write_text(PROFILE)
    return spec, venues


def loaded(paths: tuple[Path, Path]) -> list[ResolvedRunSpec]:
    spec, venues = paths
    return load(spec, {}, venues)


def with_model(paths: tuple[Path, Path], argument: str, model: str) -> None:
    _, venues = paths
    venues.write_text(f"{PROFILE}{argument} = {model}\n")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("argument", "kind", "model"),
    [
        ("fee_model", "maker_taker", MakerTakerFeeModel),
        ("fee_model", "fixed", FixedFeeModel),
        ("fill_model", "default", DefaultFillModel),
    ],
)
def test_each_model_kind_builds_its_nautilus_model(
    paths: tuple[Path, Path], argument: str, kind: str, model: type
) -> None:
    with_model(paths, argument, f'{{ kind = "{kind}", config = {CONFIGS[kind]} }}')

    [spec] = loaded(paths)
    [venue] = spec.run_config("/catalog").venues

    assert isinstance(getattr(venue, argument), model)


@pytest.mark.unit
def test_an_unknown_model_kind_names_the_known_ones(paths: tuple[Path, Path]) -> None:
    with_model(paths, "fee_model", '{ kind = "tiered", config = {} }')

    with pytest.raises(
        UnknownModelKindError, match="fee_model kind tiered; known: fixed, maker_taker"
    ):
        loaded(paths)


@pytest.mark.unit
def test_a_model_argument_without_kinds_names_none(paths: tuple[Path, Path]) -> None:
    with_model(paths, "latency_model", '{ kind = "static", config = {} }')

    with pytest.raises(
        UnknownModelKindError, match="latency_model kind static; known: none"
    ):
        loaded(paths)


@pytest.mark.unit
def test_a_model_named_by_import_path_is_refused(paths: tuple[Path, Path]) -> None:
    with_model(
        paths,
        "fee_model",
        '{ path = "nautilus_trader.execution:MakerTakerFeeModel", '
        f"config = {CONFIGS['maker_taker']} }}",
    )

    with pytest.raises(InvalidVenueProfileError, match=r"fee_model.*name a kind"):
        loaded(paths)


@pytest.mark.unit
def test_a_model_config_its_model_does_not_take_fails_on_load(
    paths: tuple[Path, Path],
) -> None:
    config = '{ maker_rate = "0.0002", taker_rate = "0.00055", bogus = 1 }'
    with_model(paths, "fee_model", f'{{ kind = "maker_taker", config = {config} }}')

    with pytest.raises(
        InvalidModelConfigError, match=r"fee_model maker_taker.*unexpected.*bogus"
    ):
        loaded(paths)


@pytest.mark.unit
def test_a_stored_spec_naming_a_model_by_path_predates_model_kinds(
    paths: tuple[Path, Path],
) -> None:
    with_model(paths, "fee_model", f'{{ kind = "fixed", config = {CONFIGS["fixed"]} }}')
    [spec] = loaded(paths)
    document = json.loads(spec.to_json())
    document["venue"]["fee_model"] = {
        "path": "nautilus_trader.execution:MakerTakerFeeModel",
        "config": {"maker_rate": "0.0002", "taker_rate": "0.00055"},
    }

    with pytest.raises(OutdatedRunError, match="predates model kinds"):
        ResolvedRunSpec.from_document(document)
