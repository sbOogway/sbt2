from datetime import date
from typing import Any

import pytest
from nautilus_trader.execution import FeeModel, MakerTakerFeeModel
from nautilus_trader.model import AccountType, Bar, MarkPriceUpdate, OmsType

from sbt2.core.spec import (
    InstrumentVenueError,
    InvalidExecutionError,
    ResolvedRunSpec,
    UnknownSpecKeyError,
    UnknownVenueError,
    load_table,
)

BYBIT = "BTCUSDT-LINEAR.BYBIT"
PERPETUAL = "BTC-PERPETUAL.DERIBIT"
OPTION = "BTC-30JAN26-100000-C.DERIBIT"
MAKER_TAKER = {
    "kind": "maker_taker",
    "config": {"maker_rate": "0.0002", "taker_rate": "0.00055"},
}
PERPETUAL_FEES = {
    "kind": "maker_taker",
    "config": {"maker_rate": "0.00015", "taker_rate": "0.00035"},
}
OPTION_FEES = {
    "kind": "capped_option",
    "config": {"maker_rate": "0.0003", "taker_rate": "0.0003", "cap_rate": "0.125"},
}
LINEAR_HASH = "00421b5d17bcdd4210488ed4921ea33f0a142a28c2efee6e59995b09c59c9df1"
PERPETUAL_HASH = "35a20aaad04d2be2d3616d0fc59034824a37ce2964c5e7ed8e9166282aa5036c"
OPTION_HASH = "b1449df8407ca21719d84c2b6616a3782669b6547f5e062052518af2eb422be6"


def linear(**changes: Any) -> dict[str, Any]:
    return {
        "strategy": "spec_strategies:MinuteLookback",
        "instruments": [BYBIT],
        "period": [date(2024, 1, 1), date(2024, 3, 1)],
        "split": {
            "validation_start": date(2024, 2, 1),
            "test_start": date(2024, 2, 15),
        },
        "part": "train",
        "capital": "10000 USDT",
        "execution": {"fee_model": MAKER_TAKER},
        **changes,
    }


def perpetual(**changes: Any) -> dict[str, Any]:
    return linear(
        instruments=[PERPETUAL],
        strategy="run_strategies:BuyThenSell",
        capital="1 BTC",
        execution={"fee_model": PERPETUAL_FEES},
        **changes,
    )


def option(**changes: Any) -> dict[str, Any]:
    return linear(
        instruments=[OPTION],
        strategy="spec_strategies:DeclaredBar",
        params={"bar": "1-HOUR-MID"},
        capital="1 BTC",
        execution={"fee_model": OPTION_FEES},
        **changes,
    )


def resolved(table: dict[str, Any]) -> ResolvedRunSpec:
    [run] = load_table(table)
    return run


def with_execution(table: dict[str, Any], **settings: Any) -> dict[str, Any]:
    return {**table, "execution": {**table["execution"], **settings}}


@pytest.mark.unit
def test_venue_is_the_venue_of_the_instruments() -> None:
    bybit, deribit = resolved(linear()), resolved(option())

    assert (bybit.venue_name, bybit.source) == ("BYBIT", "bybit")
    assert (deribit.venue_name, deribit.source) == ("DERIBIT", "deribit")
    assert "source" not in bybit.venue


@pytest.mark.unit
def test_instruments_on_two_venues_are_refused() -> None:
    table = linear(instruments=[BYBIT, PERPETUAL])

    with pytest.raises(InstrumentVenueError, match=r"2 venues, BYBIT, DERIBIT"):
        resolved(table)


@pytest.mark.unit
def test_an_instrument_of_a_venue_without_a_source_is_refused() -> None:
    with pytest.raises(UnknownVenueError, match="no source for the venue NOWHERE"):
        resolved(linear(instruments=["BTCUSDT.NOWHERE"]))


@pytest.mark.unit
@pytest.mark.parametrize("execution", [None, {}, {"default_leverage": "3"}])
def test_spec_without_fees_is_refused(execution: dict[str, Any] | None) -> None:
    table = linear()
    del table["execution"]
    if execution is not None:
        table["execution"] = execution

    with pytest.raises(InvalidExecutionError, match=r"names no fees.*fee_model"):
        resolved(table)


@pytest.mark.unit
def test_spec_fees_reach_the_venue_config() -> None:
    run = resolved(linear())
    [venue] = run.run_config("/catalog").venues

    assert run.venue["fee_model"] == MAKER_TAKER
    assert venue.name == "BYBIT"
    assert isinstance(venue.fee_model, MakerTakerFeeModel)


@pytest.mark.unit
def test_execution_table_overrides_the_asset_profile_defaults() -> None:
    table = with_execution(linear(), liquidation_enabled=True, default_leverage="5")

    venue = resolved(table).venue

    assert venue["liquidation_enabled"] is True
    assert venue["default_leverage"] == "5"
    assert venue["oms_type"] == OmsType.NETTING
    assert venue["account_type"] == AccountType.MARGIN


@pytest.mark.unit
def test_the_liquidation_key_overrides_the_execution_table() -> None:
    table = with_execution(linear(), liquidation_enabled=False)

    assert resolved({**table, "liquidation": True}).venue["liquidation_enabled"]


@pytest.mark.unit
def test_defaults_fill_what_the_execution_table_leaves_out() -> None:
    swap = resolved(linear()).venue
    options = resolved(option()).venue

    assert "fill_model" not in swap
    assert swap["liquidation_enabled"] is False
    assert options["quotes"] == {"interval_seconds": 60, "ticks": 1, "fraction": 0.05}
    assert options["delivery_fee"] == {"rate": "0.00015", "cap_rate": "0.125"}
    assert options["margin"] == {
        "base_rate": "0.15",
        "floor_rate": "0.1",
        "maintenance_rate": "0.075",
    }


@pytest.mark.unit
def test_deribit_perpetual_marks_come_from_the_bars() -> None:
    run = resolved(perpetual())

    assert run.venue["marks"] == "bars"
    assert MarkPriceUpdate not in run.data_types
    assert Bar in run.data_types


@pytest.mark.unit
def test_the_execution_table_can_take_the_marks_from_the_catalog() -> None:
    run = resolved(with_execution(perpetual(), marks="catalog"))

    assert run.venue["marks"] == "catalog"


@pytest.mark.unit
def test_a_source_that_serves_marks_leaves_the_marks_setting_out() -> None:
    assert "marks" not in resolved(linear()).venue


@pytest.mark.unit
@pytest.mark.parametrize("venue", ["test_linear", "bybit_linear"])
def test_old_venue_key_is_refused_with_a_hint(venue: str) -> None:
    with pytest.raises(UnknownSpecKeyError, match=r"remove it.*\[execution\]"):
        resolved({**linear(), "venue": venue})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("table", "pinned"),
    [(linear(), LINEAR_HASH), (perpetual(), PERPETUAL_HASH), (option(), OPTION_HASH)],
    ids=["linear", "perpetual", "option"],
)
@pytest.mark.golden
def test_migrated_spec_keeps_its_run_hash(table: dict[str, Any], pinned: str) -> None:
    assert resolved(table).hash == pinned


@pytest.mark.unit
@pytest.mark.parametrize("derived", ["name", "source", "asset_class"])
def test_the_execution_table_cannot_set_what_the_instruments_give(
    derived: str,
) -> None:
    with pytest.raises(InvalidExecutionError, match=derived):
        resolved(with_execution(linear(), **{derived: "BYBIT"}))


@pytest.mark.unit
def test_a_bybit_run_builds_a_nautilus_venue() -> None:
    [venue] = resolved(linear()).run_config("/catalog").venues

    assert venue.name == "BYBIT"
    assert venue.oms_type == OmsType.NETTING
    assert venue.liquidation_enabled is False
    assert isinstance(venue.fee_model, MakerTakerFeeModel)


@pytest.mark.unit
def test_a_deribit_option_run_builds_a_nautilus_venue() -> None:
    [venue] = resolved(option()).run_config("/catalog").venues

    assert venue.name == "DERIBIT"
    assert venue.oms_type == OmsType.NETTING
    assert venue.liquidation_enabled is False
    assert isinstance(venue.fee_model, FeeModel)


@pytest.mark.unit
def test_a_deribit_perpetual_run_builds_a_nautilus_venue() -> None:
    run = resolved(perpetual())
    [venue] = run.run_config("/catalog").venues

    assert venue.name == "DERIBIT"
    assert venue.oms_type == OmsType.NETTING
    assert venue.liquidation_enabled is False
    assert isinstance(venue.fee_model, MakerTakerFeeModel)
    assert run.venue["fee_model"]["config"] == {
        "maker_rate": "0.00015",
        "taker_rate": "0.00035",
    }


def option_venue(**settings: Any) -> dict[str, Any]:
    return dict(resolved(with_execution(option(), **settings)).venue)


@pytest.mark.unit
def test_an_option_run_reads_its_quote_settings() -> None:
    venue = option_venue(quotes={"interval_seconds": 300, "ticks": 2, "fraction": 0.1})

    assert venue["quotes"] == {"interval_seconds": 300, "ticks": 2, "fraction": 0.1}


@pytest.mark.unit
def test_a_partial_quote_table_keeps_the_defaults_of_the_rest() -> None:
    venue = option_venue(quotes={"ticks": 3})

    assert venue["quotes"] == {"interval_seconds": 60, "ticks": 3, "fraction": 0.05}


@pytest.mark.unit
def test_an_option_run_reads_its_delivery_fee_rates() -> None:
    venue = option_venue(delivery_fee={"rate": "0.0002", "cap_rate": "0.1"})

    assert venue["delivery_fee"] == {"rate": "0.0002", "cap_rate": "0.1"}


@pytest.mark.unit
def test_a_partial_delivery_fee_table_keeps_the_defaults_of_the_rest() -> None:
    venue = option_venue(delivery_fee={"rate": 0.0002})

    assert venue["delivery_fee"] == {"rate": "0.0002", "cap_rate": "0.125"}


@pytest.mark.unit
def test_an_option_run_reads_its_margin_rates() -> None:
    venue = option_venue(
        margin={"base_rate": "0.2", "floor_rate": "0.12", "maintenance_rate": "0.08"}
    )

    assert venue["margin"] == {
        "base_rate": "0.2",
        "floor_rate": "0.12",
        "maintenance_rate": "0.08",
    }


@pytest.mark.unit
def test_a_partial_margin_table_keeps_the_defaults_of_the_rest() -> None:
    venue = option_venue(margin={"floor_rate": 0.12})

    assert venue["margin"] == {
        "base_rate": "0.15",
        "floor_rate": "0.12",
        "maintenance_rate": "0.075",
    }


def settings_of(instrument: str) -> dict[str, Any]:
    return option() if instrument == OPTION else linear()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("instrument", "setting", "value"),
    [
        (OPTION, "quotes", {"spread": 1}),
        (OPTION, "quotes", {"interval_seconds": 0}),
        (OPTION, "quotes", {"fraction": -0.1}),
        (BYBIT, "quotes", {"ticks": 1}),
        (OPTION, "delivery_fee", {"charge": "1"}),
        (OPTION, "delivery_fee", {"rate": "-0.1"}),
        (OPTION, "delivery_fee", {"cap_rate": "abc"}),
        (BYBIT, "delivery_fee", {"rate": "0.1"}),
        (OPTION, "margin", {"charge": "1"}),
        (OPTION, "margin", {"base_rate": "-0.1"}),
        (OPTION, "margin", {"floor_rate": "abc"}),
        (BYBIT, "margin", {"base_rate": "0.1"}),
    ],
)
def test_an_invalid_setting_is_rejected(
    instrument: str, setting: str, value: dict[str, Any]
) -> None:
    table = with_execution(settings_of(instrument), **{setting: value})

    with pytest.raises(InvalidExecutionError, match=setting):
        resolved(table)


@pytest.mark.unit
def test_an_invalid_marks_setting_is_rejected() -> None:
    with pytest.raises(InvalidExecutionError, match="marks"):
        resolved(with_execution(linear(), marks="index"))
