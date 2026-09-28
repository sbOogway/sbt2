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

from sbt2.assets import AssetProfile, UnknownAssetClassError, asset_profile

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


def test_lookup_by_nautilus_classes_returns_the_profile() -> None:
    profile = crypto_perp()

    assert profile.asset_class == AssetClass.CRYPTOCURRENCY
    assert profile.instrument_class == InstrumentClass.SWAP


def test_unknown_classes_list_the_known_profiles() -> None:
    with pytest.raises(
        UnknownAssetClassError,
        match="no asset profile for EQUITY/SPOT; known: CRYPTOCURRENCY/SWAP",
    ):
        asset_profile(AssetClass.EQUITY, InstrumentClass.SPOT)


def test_crypto_perp_covers_nautilus_perpetuals() -> None:
    assert crypto_perp().covers(btc_perpetual())


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


def test_crypto_perp_trades_perpetuals_every_day_of_the_year() -> None:
    assert crypto_perp().days_per_year == 365


def test_crypto_perp_funding_is_settled_natively_from_funding_updates() -> None:
    assert crypto_perp().carry.data_types == (FundingRateUpdate,)


def test_crypto_perp_values_positions_at_mark_price() -> None:
    perp = crypto_perp()

    assert perp.reference_prices == (MarkPriceUpdate,)
    assert perp.valuation_price is MarkPriceUpdate


def test_crypto_perp_portfolio_uses_mark_prices() -> None:
    config = crypto_perp().portfolio_config(HOURLY)

    assert config.use_mark_prices
    assert config.snapshot_interval_ms == HOURLY


def test_crypto_perp_venue_defaults_build_a_netting_margin_venue_with_liquidation() -> (
    None
):
    defaults = crypto_perp().venue_defaults

    venue = BacktestVenueConfig(
        name="BYBIT", starting_balances=["10000 USDT"], **defaults
    )

    assert venue.oms_type == OmsType.NETTING
    assert venue.account_type == AccountType.MARGIN
    assert venue.liquidation_enabled
