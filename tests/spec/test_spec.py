import hashlib
import json
import pickle
from datetime import UTC, datetime, timedelta
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

import sbt2.spec
from sbt2.spec import (
    CandleBarError,
    DateSplit,
    DuplicateRunError,
    EmptyListError,
    FractionSplit,
    InstrumentVenueError,
    InvalidVenueProfileError,
    MissingSplitError,
    ResolvedRunSpec,
    SpecError,
    UnknownBarSourceError,
    UnknownPartError,
    UnknownSpecKeyError,
    UnknownSplitError,
    UnknownVenueProfileError,
    load,
)
from sbt2.strategy import UnknownParameterError

BTC = "BTCUSDT-LINEAR.BYBIT"
ETH = "ETHUSDT-LINEAR.BYBIT"
SPEC = f"""
strategy = "spec_strategies:MinuteLookback"
instruments = ["{BTC}"]
period = [2024-01-01, 2024-03-01]
split = {{ validation_start = 2024-02-01, test_start = 2024-02-15 }}
part = "train"
venue = "test_linear"
capital = "10000 USDT"

[params]
lookback = 30
"""
VENUES = """
[test_linear]
name = "BYBIT"
source = "bybit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
default_leverage = "10"
fee_model = { path = "nautilus_trader.execution:MakerTakerFeeModel", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }

[seeded_linear]
name = "BYBIT"
source = "bybit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
fill_model = { path = "nautilus_trader.execution:DefaultFillModel", config = { prob_fill_on_limit = 0.5, prob_slippage = 0.1 } }

[unliquidated_linear]
name = "BYBIT"
source = "bybit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
liquidation_enabled = false
fee_model = { path = "nautilus_trader.execution:MakerTakerFeeModel", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }

[other_source]
name = "BYBIT"
source = "mirror"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
default_leverage = "10"
fee_model = { path = "nautilus_trader.execution:MakerTakerFeeModel", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }
"""
SOURCELESS = """
[sourceless]
name = "BYBIT"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
"""
DECLARED_BAR = "spec_strategies:DeclaredBar"
START = datetime(2024, 1, 1, tzinfo=UTC)
END = datetime(2024, 2, 1, tzinfo=UTC)
DATA_START = datetime(2023, 12, 31, 23, 30, tzinfo=UTC)
VALIDATION = (datetime(2024, 2, 1, tzinfo=UTC), datetime(2024, 2, 15, tzinfo=UTC))
BY_DATE = DateSplit(validation_start="2024-02-01", test_start="2024-02-15")


@pytest.fixture
def paths(tmp_path: Path) -> tuple[Path, Path]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)
    venues.write_text(VENUES)
    return spec, venues


def resolved(paths: tuple[Path, Path], **overrides: Any) -> ResolvedRunSpec:
    [spec] = loaded(paths, **overrides)
    return spec


def loaded(paths: tuple[Path, Path], **overrides: Any) -> list[ResolvedRunSpec]:
    spec, venues = paths
    return load(spec, overrides, venues)


def without(paths: tuple[Path, Path], key: str) -> tuple[Path, Path]:
    """The spec file with the line setting ``key`` dropped."""
    spec, venues = paths
    lines = spec.read_text().splitlines(keepends=True)
    spec.write_text("".join(each for each in lines if not each.startswith(key)))
    return spec, venues


@pytest.mark.unit
def test_strategy_run_has_instrument_ids_and_params_with_defaults(
    paths: tuple[Path, Path],
) -> None:
    run = resolved(paths).strategy

    assert run.strategy == "spec_strategies:MinuteLookback"
    assert run.instruments == [InstrumentId.from_str(BTC)]
    assert run.params == {"lookback": 30, "stop": Decimal("0.02")}
    assert run.trade_start == START


@pytest.mark.unit
def test_venue_profile_names_the_asset_profile(paths: tuple[Path, Path]) -> None:
    asset = resolved(paths).asset

    assert (asset.asset_class, asset.instrument_class) == (
        AssetClass.CRYPTOCURRENCY,
        InstrumentClass.SWAP,
    )


@pytest.mark.unit
def test_the_venue_profile_names_the_data_source(paths: tuple[Path, Path]) -> None:
    spec = resolved(paths)

    assert spec.source == "bybit"
    assert "source" not in spec.venue


@pytest.mark.unit
def test_the_data_source_is_not_part_of_the_spec_hash(
    paths: tuple[Path, Path],
) -> None:
    assert resolved(paths).hash == resolved(paths, venue="other_source").hash


@pytest.mark.unit
def test_a_venue_profile_without_a_source_fails(paths: tuple[Path, Path]) -> None:
    spec, venues = paths
    venues.write_text(SOURCELESS)

    with pytest.raises(InvalidVenueProfileError, match="sourceless.* source"):
        load(spec, {"venue": "sourceless"}, venues)


@pytest.mark.unit
def test_venue_arguments_start_from_the_asset_defaults(
    paths: tuple[Path, Path],
) -> None:
    venue = resolved(paths).venue

    assert venue["oms_type"] == OmsType.NETTING
    assert venue["account_type"] == AccountType.MARGIN
    assert venue["liquidation_enabled"] is False
    assert venue["default_leverage"] == "10"
    assert venue["starting_balances"] == ["10000 USDT"]


@pytest.mark.unit
def test_liquidation_follows_the_venue_profile_by_default(
    paths: tuple[Path, Path],
) -> None:
    venue = resolved(paths, venue="unliquidated_linear").venue

    assert venue["liquidation_enabled"] is False


@pytest.mark.unit
def test_the_liquidation_key_overrides_the_venue_profile(
    paths: tuple[Path, Path],
) -> None:
    unset = resolved(paths, venue="unliquidated_linear")
    liquidated = resolved(paths, venue="unliquidated_linear", liquidation=True)

    assert liquidated.venue["liquidation_enabled"] is True
    assert liquidated.hash != unset.hash


@pytest.mark.unit
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


@pytest.mark.unit
def test_bars_come_from_trades_by_default(paths: tuple[Path, Path]) -> None:
    spec = resolved(paths)

    streamed = [each["data_type"] for each in spec.data]
    assert NautilusDataType.TradeTick in streamed
    assert NautilusDataType.Bar not in streamed
    assert spec.hash == resolved(paths, bars="trades").hash
    assert spec.hash == (
        "7488ea117667a2969073e4b9693d12515de950a2690c3a65857aeedbbdfc8d5b"
    )


@pytest.mark.unit
def test_a_candle_run_streams_one_minute_candles_instead_of_trades(
    paths: tuple[Path, Path],
) -> None:
    data = resolved(paths, bars="candles").data

    assert [each["data_type"] for each in data] == [
        NautilusDataType.Bar,
        NautilusDataType.FundingRateUpdate,
        NautilusDataType.MarkPriceUpdate,
    ]
    assert data[0]["bar_types"] == [f"{BTC}-1-MINUTE-LAST-EXTERNAL"]
    assert {(each["start_time"], each["end_time"]) for each in data} == {
        (DATA_START, END)
    }


@pytest.mark.unit
def test_a_candle_run_has_the_strategy_aggregate_from_candles(
    paths: tuple[Path, Path],
) -> None:
    assert resolved(paths).strategy.aggregated_from is None
    assert (
        resolved(paths, bars="candles").strategy.aggregated_from == "1-MINUTE-EXTERNAL"
    )


@pytest.mark.unit
def test_the_bar_source_changes_the_hash(paths: tuple[Path, Path]) -> None:
    assert resolved(paths, bars="candles").hash != resolved(paths).hash


@pytest.mark.unit
@pytest.mark.parametrize(
    "bar",
    ["1-MINUTE-LAST", "15-MINUTE-LAST", "1-HOUR-LAST", "4-HOUR-LAST", "1-DAY-LAST"],
)
def test_whole_minute_bars_are_built_from_candles(
    paths: tuple[Path, Path], bar: str
) -> None:
    spec = resolved(paths, strategy=DECLARED_BAR, params={"bar": bar}, bars="candles")

    assert spec.data[0]["data_type"] == NautilusDataType.Bar


@pytest.mark.unit
@pytest.mark.parametrize(
    "bar",
    [
        "30-SECOND-LAST",
        "500-MILLISECOND-LAST",
        "1-HOUR-BID",
        "1-HOUR-ASK",
        "1-HOUR-MID",
        "100-TICK-LAST",
        "10-VOLUME-LAST",
    ],
)
def test_bars_candles_cannot_build_are_refused(
    paths: tuple[Path, Path], bar: str
) -> None:
    with pytest.raises(CandleBarError, match=bar):
        resolved(paths, strategy=DECLARED_BAR, params={"bar": bar}, bars="candles")


@pytest.mark.unit
def test_an_unknown_bar_source_is_refused(paths: tuple[Path, Path]) -> None:
    with pytest.raises(UnknownBarSourceError, match="trades, candles"):
        resolved(paths, bars="quotes")


@pytest.mark.unit
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


@pytest.mark.unit
def test_engine_arguments_reach_the_engine_config(paths: tuple[Path, Path]) -> None:
    engine = {"shutdown_on_error": True, "run_analysis": False}

    config = resolved(paths).run_config("/catalog", engine).engine

    assert config.shutdown_on_error
    assert not config.run_analysis
    assert config.portfolio is not None


@pytest.mark.unit
def test_portfolio_samples_equity_at_the_interval_in_mark_prices(
    paths: tuple[Path, Path],
) -> None:
    config = resolved(paths, equity_interval="15m").run_config("/catalog")

    portfolio = config.engine.portfolio
    assert portfolio is not None
    assert portfolio.snapshot_interval_ms == 15 * 60_000
    assert portfolio.use_mark_prices


@pytest.mark.unit
def test_equity_interval_defaults_to_one_hour(paths: tuple[Path, Path]) -> None:
    assert resolved(paths).equity_interval_ms == 3_600_000


@pytest.mark.unit
def test_malformed_equity_interval_fails(paths: tuple[Path, Path]) -> None:
    with pytest.raises(ValueError, match="1h"):
        resolved(paths, equity_interval="an hour")


@pytest.mark.unit
def test_overrides_replace_file_values(paths: tuple[Path, Path]) -> None:
    spec = resolved(paths, period=["2024-01-15", "2024-03-01"], params={"lookback": 5})

    assert spec.start == datetime(2024, 1, 15, tzinfo=UTC)
    assert spec.strategy.params["lookback"] == 5


@pytest.mark.unit
def test_hash_is_stable_for_the_same_spec(paths: tuple[Path, Path]) -> None:
    first, second = resolved(paths), resolved(paths)

    assert first.hash == second.hash
    assert len(first.hash) == 64


@pytest.mark.unit
def test_json_is_the_hashed_document(paths: tuple[Path, Path]) -> None:
    spec = resolved(paths)

    document = json.loads(spec.to_json())
    assert document["strategy"]["params"] == {"lookback": 30, "stop": "0.02"}
    assert document["start"] == "2024-01-01T00:00:00+00:00"
    assert hashlib.sha256(spec.to_json().encode()).hexdigest() == spec.hash


@pytest.mark.unit
@pytest.mark.parametrize(
    "overrides",
    [
        {"params": {"lookback": 31}},
        {"period": ["2024-01-02", "2024-03-01"]},
        {"capital": "20000 USDT"},
        {"equity_interval": "30m"},
        {"instruments": ["ETHUSDT-LINEAR.BYBIT"]},
    ],
)
def test_hash_changes_with_the_backtest(
    paths: tuple[Path, Path], overrides: dict[str, Any]
) -> None:
    assert resolved(paths, **overrides).hash != resolved(paths).hash


@pytest.mark.unit
def test_hash_ignores_the_seed_without_a_random_fill_model(
    paths: tuple[Path, Path],
) -> None:
    assert resolved(paths, seed=7).hash == resolved(paths).hash


@pytest.mark.unit
def test_seed_goes_to_the_fill_model(paths: tuple[Path, Path]) -> None:
    seeded = resolved(paths, venue="seeded_linear", seed=7)

    assert seeded.venue["fill_model"]["config"]["random_seed"] == 7
    assert seeded.hash != resolved(paths, venue="seeded_linear").hash
    [venue] = seeded.run_config("/catalog").venues
    assert venue.fill_model is not None


@pytest.mark.unit
def test_unknown_parameter_fails_listing_the_valid_ones(
    paths: tuple[Path, Path],
) -> None:
    with pytest.raises(UnknownParameterError, match="valid: lookback, stop"):
        resolved(paths, params={"lookbak": 5})


@pytest.mark.unit
def test_unknown_venue_profile_fails_listing_the_known_ones(
    paths: tuple[Path, Path],
) -> None:
    with pytest.raises(UnknownVenueProfileError, match="seeded_linear, test_linear"):
        resolved(paths, venue="binance_linear")


@pytest.mark.unit
def test_instrument_on_another_venue_fails(paths: tuple[Path, Path]) -> None:
    with pytest.raises(InstrumentVenueError, match="BTCUSDT-LINEAR.BINANCE"):
        resolved(paths, instruments=[BTC, "BTCUSDT-LINEAR.BINANCE"])


@pytest.mark.unit
def test_unknown_spec_key_fails_listing_the_valid_ones(
    paths: tuple[Path, Path],
) -> None:
    with pytest.raises(
        UnknownSpecKeyError, match="symbols .* valid: bars, capital, equity_interval"
    ):
        resolved(paths, symbols=["BTCUSDT"])


@pytest.mark.unit
def test_the_period_is_utc(paths: tuple[Path, Path]) -> None:
    spec = resolved(
        paths,
        period=[datetime.fromisoformat("2024-01-01T02:00:00+02:00"), "2024-03-01"],
    )

    assert spec.start == START


@pytest.mark.unit
def test_the_part_sets_the_run_dates(paths: tuple[Path, Path]) -> None:
    spec = resolved(paths, part="validation")

    config = spec.run_config("/catalog")
    assert (spec.start, spec.end) == VALIDATION
    assert (config.start, config.end) == tuple(map(dt_to_unix_nanos, VALIDATION))
    assert spec.strategy.trade_start == VALIDATION[0]


@pytest.mark.unit
def test_warmup_reads_data_from_before_the_part(paths: tuple[Path, Path]) -> None:
    data = resolved(paths, part="validation").data

    assert {each["start_time"] for each in data} == {
        datetime(2024, 1, 31, 23, 30, tzinfo=UTC)
    }


@pytest.mark.unit
def test_the_resolved_spec_carries_the_split_and_part(
    paths: tuple[Path, Path],
) -> None:
    spec = resolved(paths)

    assert (spec.split, spec.part) == (BY_DATE, "train")


@pytest.mark.unit
def test_the_split_and_part_are_in_the_hashed_document(
    paths: tuple[Path, Path],
) -> None:
    document = json.loads(resolved(paths).to_json())

    assert document["split"] == {
        "kind": "Split",
        "validation_start": "2024-02-01T00:00:00+00:00",
        "test_start": "2024-02-15T00:00:00+00:00",
    }
    assert document["part"] == "train"


@pytest.mark.unit
def test_the_same_dates_under_another_split_change_the_hash(
    paths: tuple[Path, Path],
) -> None:
    by_date = resolved(paths)
    by_fraction = resolved(paths, split=FractionSplit(validation=0.25, test=14 / 60))

    assert (by_fraction.start, by_fraction.end) == (by_date.start, by_date.end)
    assert by_fraction.hash != by_date.hash


@pytest.mark.unit
def test_a_splitter_can_be_given_as_an_override(paths: tuple[Path, Path]) -> None:
    split = FractionSplit(validation=0.25, test=0.25)

    assert resolved(paths, split=split).split == split


def with_params(paths: tuple[Path, Path], lines: str) -> tuple[Path, Path]:
    """The spec file with its ``[params]`` table holding ``lines``."""
    spec, venues = paths
    spec.write_text(spec.read_text().replace("lookback = 30\n", lines))
    return spec, venues


def params(runs: list[ResolvedRunSpec]) -> list[dict[str, Any]]:
    return [dict(each.strategy.params) for each in runs]


@pytest.mark.unit
def test_a_spec_with_a_part_loads_as_one_run(paths: tuple[Path, Path]) -> None:
    [spec] = loaded(paths)

    assert spec.part == "train"


@pytest.mark.unit
def test_a_parameter_list_expands_into_one_run_per_value(
    paths: tuple[Path, Path],
) -> None:
    short, long = loaded(with_params(paths, "lookback = [20, 50]\n"))

    assert (short.strategy.params["lookback"], long.strategy.params["lookback"]) == (
        20,
        50,
    )
    assert short.data[0]["start_time"] == START - timedelta(minutes=20)
    assert long.data[0]["start_time"] == START - timedelta(minutes=50)


@pytest.mark.unit
def test_parameter_lists_expand_into_their_cartesian_product(
    paths: tuple[Path, Path],
) -> None:
    runs = loaded(with_params(paths, 'lookback = [20, 50]\nstop = ["0.01", "0.02"]\n'))

    assert params(runs) == [
        {"lookback": 20, "stop": Decimal("0.01")},
        {"lookback": 20, "stop": Decimal("0.02")},
        {"lookback": 50, "stop": Decimal("0.01")},
        {"lookback": 50, "stop": Decimal("0.02")},
    ]


@pytest.mark.unit
def test_parameter_lists_expand_with_every_part(paths: tuple[Path, Path]) -> None:
    runs = loaded(with_params(without(paths, "part"), "lookback = [20, 50]\n"))

    assert [(each.part, each.strategy.params["lookback"]) for each in runs] == [
        ("train", 20),
        ("train", 50),
        ("validation", 20),
        ("validation", 50),
    ]


@pytest.mark.unit
def test_the_runs_come_in_part_then_parameter_order(
    paths: tuple[Path, Path],
) -> None:
    lines = 'stop = ["0.02", "0.01"]\nlookback = [50, 20]\n'
    expanded = with_params(without(paths, "part"), lines)
    runs = loaded(expanded)

    order = [
        (each.part, str(each.strategy.params["stop"]), each.strategy.params["lookback"])
        for each in runs
    ]
    assert order == [
        (part, stop, lookback)
        for part in ("train", "validation")
        for stop in ("0.02", "0.01")
        for lookback in (50, 20)
    ]
    assert [each.hash for each in loaded(expanded)] == [each.hash for each in runs]


@pytest.mark.unit
def test_instruments_stay_one_universe(paths: tuple[Path, Path]) -> None:
    [spec] = loaded(paths, instruments=[BTC, ETH])

    assert spec.strategy.instruments == [
        InstrumentId.from_str(BTC),
        InstrumentId.from_str(ETH),
    ]


@pytest.mark.unit
def test_a_parameter_list_given_as_an_override_expands(
    paths: tuple[Path, Path],
) -> None:
    runs = loaded(paths, params={"lookback": [20, 50]})

    assert [each["lookback"] for each in params(runs)] == [20, 50]


@pytest.mark.unit
def test_one_invalid_combination_fails_the_whole_load(
    paths: tuple[Path, Path],
) -> None:
    bars = {"bar": ["1-HOUR-LAST", "1-SECOND-LAST"]}

    with pytest.raises(CandleBarError) as error:
        loaded(paths, strategy=DECLARED_BAR, params=bars, bars="candles")

    assert error.value.__notes__ == [
        "in the train run with bar='1-SECOND-LAST'",
    ]


@pytest.mark.unit
def test_a_repeated_value_fails_as_a_duplicate_run(paths: tuple[Path, Path]) -> None:
    with pytest.raises(DuplicateRunError, match="lookback=20"):
        loaded(with_params(paths, "lookback = [20, 20]\n"))


@pytest.mark.unit
def test_values_that_resolve_to_the_same_run_fail_as_duplicates(
    paths: tuple[Path, Path],
) -> None:
    with pytest.raises(DuplicateRunError, match="stop='0.02' .* stop=0.02"):
        loaded(with_params(paths, 'stop = ["0.02", 0.02]\n'))


@pytest.mark.unit
def test_an_empty_list_fails_naming_its_key(paths: tuple[Path, Path]) -> None:
    with pytest.raises(EmptyListError, match="lookback"):
        loaded(with_params(paths, "lookback = []\n"))


@pytest.mark.unit
def test_an_empty_list_of_parts_fails(paths: tuple[Path, Path]) -> None:
    with pytest.raises(EmptyListError, match="part"):
        loaded(paths, part=[])


@pytest.mark.unit
def test_start_and_end_are_no_longer_spec_keys(paths: tuple[Path, Path]) -> None:
    with pytest.raises(
        UnknownSpecKeyError, match="start .* valid: .*params, part, period, seed, split"
    ):
        resolved(paths, start="2024-01-01")


@pytest.mark.unit
def test_a_spec_without_a_split_fails(paths: tuple[Path, Path]) -> None:
    with pytest.raises(MissingSplitError):
        resolved(without(paths, "split"))


@pytest.mark.unit
def test_without_a_part_a_spec_expands_into_a_train_and_a_validation_run(
    paths: tuple[Path, Path],
) -> None:
    train, validation = loaded(without(paths, "part"))

    assert (train.part, train.start, train.end) == ("train", START, END)
    assert (validation.part, (validation.start, validation.end)) == (
        "validation",
        VALIDATION,
    )


@pytest.mark.unit
def test_a_list_of_parts_expands_into_one_run_per_part(
    paths: tuple[Path, Path],
) -> None:
    runs = loaded(paths, part=["validation", "test"])

    assert [each.part for each in runs] == ["validation", "test"]


@pytest.mark.unit
def test_an_unknown_part_fails_listing_the_parts(paths: tuple[Path, Path]) -> None:
    with pytest.raises(UnknownPartError, match="holdout.* train, validation, test"):
        resolved(paths, part="holdout")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("table", "keys"),
    [
        ({"kind": "walk_forward"}, "kind"),
        ({"validation": 0.2, "test_start": "2024-02-15"}, "test_start, validation"),
        ({"validation": 0.2}, "validation"),
    ],
)
def test_a_split_table_that_fits_no_splitter_fails_listing_the_forms(
    paths: tuple[Path, Path], table: dict[str, Any], keys: str
) -> None:
    with pytest.raises(
        UnknownSplitError,
        match=f"keys {keys} fit no split.*test and validation.*"
        "test_start and validation_start",
    ):
        resolved(paths, split=table)


@pytest.mark.unit
def test_a_split_table_of_fractions_resolves(paths: tuple[Path, Path]) -> None:
    spec_file, _ = paths
    spec_file.write_text(
        spec_file.read_text().replace(
            "split = { validation_start = 2024-02-01, test_start = 2024-02-15 }",
            "split = { validation = 0.25, test = 0.25 }",
        )
    )

    spec = resolved(paths)

    assert spec.split == FractionSplit(validation=0.25, test=0.25)
    assert (spec.start, spec.end) == (START, datetime(2024, 1, 31, tzinfo=UTC))


@pytest.mark.unit
@pytest.mark.parametrize("bars", ["trades", "candles"])
def test_a_resolved_spec_survives_pickling(paths: tuple[Path, Path], bars: str) -> None:
    spec = resolved(paths, bars=bars)

    copy = pickle.loads(pickle.dumps(spec))

    assert copy.hash == spec.hash
    assert copy.to_json() == spec.to_json()
    config, copied = spec.run_config("/catalog"), copy.run_config("/catalog")
    assert repr(copied.venues) == repr(config.venues)
    assert repr(copied.data) == repr(config.data)


@pytest.mark.unit
def test_every_spec_error_is_a_spec_error() -> None:
    errors = [
        each
        for each in vars(sbt2.spec).values()
        if isinstance(each, type) and issubclass(each, Exception)
    ]

    assert len(errors) > 1
    assert issubclass(SpecError, ValueError)
    assert [each for each in errors if not issubclass(each, SpecError)] == []
