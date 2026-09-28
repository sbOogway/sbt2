import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.execution import MakerTakerFeeModel
from nautilus_trader.model import (
    AccountType,
    AssetClass,
    InstrumentClass,
    InstrumentId,
    NautilusDataType,
    OmsType,
)

from sbt2.spec import (
    InstrumentVenueError,
    ResolvedRunSpec,
    UnknownSpecKeyError,
    UnknownVenueProfileError,
    load,
)
from sbt2.strategy import UnknownParameterError

BTC = "BTCUSDT-LINEAR.BYBIT"
SPEC = f"""
strategy = "spec_strategies:MinuteLookback"
instruments = ["{BTC}"]
start = 2024-01-01
end = 2024-02-01
venue = "test_linear"
capital = "10000 USDT"

[params]
lookback = 30
"""
VENUES = """
[test_linear]
name = "BYBIT"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
default_leverage = "10"
fee_model = { path = "nautilus_trader.execution:MakerTakerFeeModel", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }

[seeded_linear]
name = "BYBIT"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
fill_model = { path = "nautilus_trader.execution:DefaultFillModel", config = { prob_fill_on_limit = 0.5, prob_slippage = 0.1 } }
"""
START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 2, 1, tzinfo=UTC)
DATA_START = datetime(2023, 12, 31, 23, 30, tzinfo=UTC)


@pytest.fixture
def paths(tmp_path: Path) -> tuple[Path, Path]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)
    venues.write_text(VENUES)
    return spec, venues


def resolved(paths: tuple[Path, Path], **overrides: Any) -> ResolvedRunSpec:
    spec, venues = paths
    return load(spec, overrides, venues)


def test_strategy_run_has_instrument_ids_and_params_with_defaults(
    paths: tuple[Path, Path],
) -> None:
    run = resolved(paths).strategy

    assert run.strategy == "spec_strategies:MinuteLookback"
    assert run.instruments == [InstrumentId.from_str(BTC)]
    assert run.params == {"lookback": 30, "stop": Decimal("0.02")}
    assert run.trade_start == START


def test_venue_profile_names_the_asset_profile(paths: tuple[Path, Path]) -> None:
    asset = resolved(paths).asset

    assert (asset.asset_class, asset.instrument_class) == (
        AssetClass.CRYPTOCURRENCY,
        InstrumentClass.SWAP,
    )


def test_venue_arguments_start_from_the_asset_defaults(
    paths: tuple[Path, Path],
) -> None:
    venue = resolved(paths).venue

    assert venue["oms_type"] == OmsType.NETTING
    assert venue["account_type"] == AccountType.MARGIN
    assert venue["liquidation_enabled"] is True
    assert venue["default_leverage"] == "10"
    assert venue["starting_balances"] == ["10000 USDT"]


def test_data_covers_declared_bars_and_the_asset_streams_from_warmup(
    paths: tuple[Path, Path],
) -> None:
    data = resolved(paths).data

    assert [each["data_type"] for each in data] == [
        NautilusDataType.FundingRateUpdate,
        NautilusDataType.MarkPriceUpdate,
        NautilusDataType.TradeTick,
    ]
    assert {(each["start_time"], each["end_time"]) for each in data} == {
        (DATA_START, END)
    }


def test_run_config_is_built_from_the_resolved_arguments(
    paths: tuple[Path, Path],
) -> None:
    config = resolved(paths).run_config("/catalog", chunk_size=1000)

    [venue] = config.venues
    assert venue.name == "BYBIT"
    assert isinstance(venue.fee_model, MakerTakerFeeModel)
    assert venue.default_leverage == Decimal(10)
    assert {each.catalog_path for each in config.data} == {"/catalog"}
    assert {each.start_time for each in config.data} == {dt_to_unix_nanos(DATA_START)}
    assert (config.start, config.end) == (
        dt_to_unix_nanos(START),
        dt_to_unix_nanos(END),
    )
    assert config.chunk_size == 1000


def test_portfolio_samples_equity_at_the_interval_in_mark_prices(
    paths: tuple[Path, Path],
) -> None:
    config = resolved(paths, equity_interval="15m").run_config("/catalog")

    portfolio = config.engine.portfolio
    assert portfolio is not None
    assert portfolio.snapshot_interval_ms == 15 * 60_000
    assert portfolio.use_mark_prices


def test_equity_interval_defaults_to_one_hour(paths: tuple[Path, Path]) -> None:
    assert resolved(paths).equity_interval_ms == 3_600_000


def test_malformed_equity_interval_fails(paths: tuple[Path, Path]) -> None:
    with pytest.raises(ValueError, match="1h"):
        resolved(paths, equity_interval="an hour")


def test_overrides_replace_file_values(paths: tuple[Path, Path]) -> None:
    spec = resolved(paths, start="2024-01-15", params={"lookback": 5})

    assert spec.start == datetime(2024, 1, 15, tzinfo=UTC)
    assert spec.strategy.params["lookback"] == 5


def test_hash_is_stable_for_the_same_spec(paths: tuple[Path, Path]) -> None:
    first, second = resolved(paths), resolved(paths)

    assert first.hash == second.hash
    assert len(first.hash) == 64


def test_json_is_the_hashed_document(paths: tuple[Path, Path]) -> None:
    spec = resolved(paths)

    document = json.loads(spec.to_json())
    assert document["strategy"]["params"] == {"lookback": 30, "stop": "0.02"}
    assert document["start"] == "2024-01-01T00:00:00+00:00"
    assert hashlib.sha256(spec.to_json().encode()).hexdigest() == spec.hash


@pytest.mark.parametrize(
    "overrides",
    [
        {"params": {"lookback": 31}},
        {"end": "2024-02-02"},
        {"capital": "20000 USDT"},
        {"equity_interval": "30m"},
        {"instruments": ["ETHUSDT-LINEAR.BYBIT"]},
    ],
)
def test_hash_changes_with_the_backtest(
    paths: tuple[Path, Path], overrides: dict[str, Any]
) -> None:
    assert resolved(paths, **overrides).hash != resolved(paths).hash


def test_hash_ignores_the_seed_without_a_random_fill_model(
    paths: tuple[Path, Path],
) -> None:
    assert resolved(paths, seed=7).hash == resolved(paths).hash


def test_seed_goes_to_the_fill_model(paths: tuple[Path, Path]) -> None:
    seeded = resolved(paths, venue="seeded_linear", seed=7)

    assert seeded.venue["fill_model"]["config"]["random_seed"] == 7
    assert seeded.hash != resolved(paths, venue="seeded_linear").hash
    [venue] = seeded.run_config("/catalog").venues
    assert venue.fill_model is not None


def test_unknown_parameter_fails_listing_the_valid_ones(
    paths: tuple[Path, Path],
) -> None:
    with pytest.raises(UnknownParameterError, match="valid: lookback, stop"):
        resolved(paths, params={"lookbak": 5})


def test_unknown_venue_profile_fails_listing_the_known_ones(
    paths: tuple[Path, Path],
) -> None:
    with pytest.raises(UnknownVenueProfileError, match="seeded_linear, test_linear"):
        resolved(paths, venue="binance_linear")


def test_instrument_on_another_venue_fails(paths: tuple[Path, Path]) -> None:
    with pytest.raises(InstrumentVenueError, match="BTCUSDT-LINEAR.BINANCE"):
        resolved(paths, instruments=[BTC, "BTCUSDT-LINEAR.BINANCE"])


def test_unknown_spec_key_fails_listing_the_valid_ones(
    paths: tuple[Path, Path],
) -> None:
    with pytest.raises(UnknownSpecKeyError, match="symbols .* valid: capital, end"):
        resolved(paths, symbols=["BTCUSDT"])


def test_dates_are_utc(paths: tuple[Path, Path]) -> None:
    spec = resolved(paths, start=datetime.fromisoformat("2024-01-01T02:00:00+02:00"))

    assert spec.start == START
