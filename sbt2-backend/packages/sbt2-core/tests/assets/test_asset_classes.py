from decimal import Decimal
from types import SimpleNamespace

import pytest
from nautilus_trader.backtest import BacktestVenueConfig
from nautilus_trader.model import (
    AccountType,
    AssetClass,
    CryptoPerpetual,
    Currency,
    FundingRateUpdate,
    InstrumentClass,
    InstrumentId,
    MarkPriceUpdate,
    OmsType,
    Price,
    Quantity,
    Symbol,
)

from sbt2.core.assets import (
    AssetProfile,
    NoTakerRateError,
    UnknownAssetClassError,
    asset_profile,
)

HOURLY = 3_600_000


def crypto_perp() -> AssetProfile:
    return asset_profile(AssetClass.CRYPTOCURRENCY, InstrumentClass.SWAP)


def btc_perpetual() -> CryptoPerpetual:
    usdt = Currency.from_str("USDT")
    return CryptoPerpetual(
        InstrumentId.from_str("BTCUSDT-PERP.BYBIT"),
        Symbol("BTCUSDT"),
        Currency.from_str("BTC"),
        usdt,
        usdt,
        False,
        1,
        3,
        Price.from_str("0.1"),
        Quantity.from_str("0.001"),
        0,
        0,
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
    )


@pytest.mark.unit
def test_lookup_by_nautilus_classes_returns_the_profile() -> None:
    profile = crypto_perp()

    assert profile.asset_class == AssetClass.CRYPTOCURRENCY
    assert profile.instrument_class == InstrumentClass.SWAP


@pytest.mark.unit
def test_unknown_classes_list_the_known_profiles() -> None:
    with pytest.raises(
        UnknownAssetClassError,
        match="no asset profile for EQUITY/SPOT; known: CRYPTOCURRENCY/SWAP",
    ):
        asset_profile(AssetClass.EQUITY, InstrumentClass.SPOT)


@pytest.mark.unit
def test_crypto_perp_covers_nautilus_perpetuals() -> None:
    assert crypto_perp().covers(btc_perpetual())


@pytest.mark.unit
@pytest.mark.parametrize(
    ("asset_class", "instrument_class"),
    [
        (AssetClass.CRYPTOCURRENCY, InstrumentClass.SPOT),
        (AssetClass.EQUITY, InstrumentClass.SWAP),
    ],
)
def test_crypto_perp_does_not_cover_other_instruments(
    asset_class: AssetClass, instrument_class: InstrumentClass
) -> None:
    other = SimpleNamespace(asset_class=asset_class, instrument_class=instrument_class)

    assert not crypto_perp().covers(other)


@pytest.mark.unit
def test_crypto_perp_trades_perpetuals_every_day_of_the_year() -> None:
    assert crypto_perp().days_per_year == 365


@pytest.mark.unit
def test_crypto_perp_funding_is_settled_natively_from_funding_updates() -> None:
    assert crypto_perp().carry.data_types == (FundingRateUpdate,)


@pytest.mark.unit
def test_crypto_perp_values_positions_at_mark_price() -> None:
    perp = crypto_perp()

    assert perp.reference_prices == (MarkPriceUpdate,)
    assert perp.valuation_price is MarkPriceUpdate


@pytest.mark.unit
def test_crypto_perp_portfolio_uses_mark_prices() -> None:
    config = crypto_perp().portfolio_config(HOURLY)

    assert config.use_mark_prices
    assert config.snapshot_interval_ms == HOURLY


@pytest.mark.unit
def test_crypto_perp_buy_and_hold_uses_the_mark_price_and_the_entry_fee_only() -> None:
    convention = crypto_perp().buy_and_hold
    fee_model = {
        "kind": "maker_taker",
        "config": {"maker_rate": "0.0002", "taker_rate": "0.00055"},
    }

    assert convention.price is MarkPriceUpdate
    assert convention.carry.data_types == ()
    assert convention.entry_fee({"fee_model": fee_model}) == Decimal("0.00055")


@pytest.mark.unit
def test_an_entry_fee_needs_a_fee_model_with_a_taker_rate() -> None:
    fixed = {"kind": "fixed", "config": {}}

    with pytest.raises(NoTakerRateError, match="fixed has no taker rate"):
        crypto_perp().buy_and_hold.entry_fee({"fee_model": fixed})


@pytest.mark.unit
def test_crypto_perp_venue_defaults_build_a_netting_margin_venue_without_liquidation() -> (
    None
):
    defaults = crypto_perp().venue_defaults

    venue = BacktestVenueConfig(
        name="BYBIT", starting_balances=["10000 USDT"], **defaults
    )

    assert venue.oms_type == OmsType.NETTING
    assert venue.account_type == AccountType.MARGIN
    assert venue.liquidation_enabled is False
