import pytest
from nautilus_trader.backtest import BacktestVenueConfig
from nautilus_trader.model import (
    AccountType,
    CryptoPerpetual,
    FundingRateUpdate,
    MarkPriceUpdate,
    OmsType,
)

from sbt2.assets import BuyAndHold, UnknownAssetClassError, asset_class

HOURLY = 3_600_000


def test_lookup_by_name_returns_the_asset_class() -> None:
    assert asset_class("crypto_perp").name == "crypto_perp"


def test_unknown_name_lists_the_known_asset_classes() -> None:
    with pytest.raises(UnknownAssetClassError, match="known: crypto_perp"):
        asset_class("equity")


def test_crypto_perp_trades_perpetuals_every_day_of_the_year() -> None:
    perp = asset_class("crypto_perp")

    assert perp.instrument_type is CryptoPerpetual
    assert perp.days_per_year == 365


def test_crypto_perp_funding_is_settled_natively_from_funding_updates() -> None:
    carry = asset_class("crypto_perp").carry

    assert carry.name == "funding"
    assert carry.data_types == (FundingRateUpdate,)
    assert carry.module is None


def test_crypto_perp_values_positions_at_mark_price() -> None:
    perp = asset_class("crypto_perp")

    assert perp.reference_prices == (MarkPriceUpdate,)
    assert perp.valuation_price is MarkPriceUpdate


def test_crypto_perp_portfolio_uses_mark_prices() -> None:
    config = asset_class("crypto_perp").portfolio_config(HOURLY)

    assert config.use_mark_prices
    assert config.snapshot_interval_ms == HOURLY


def test_crypto_perp_venue_defaults_build_a_netting_margin_venue_with_liquidation() -> (
    None
):
    defaults = asset_class("crypto_perp").venue_defaults

    venue = BacktestVenueConfig(
        name="BYBIT", starting_balances=["10000 USDT"], **defaults
    )

    assert venue.oms_type == OmsType.NETTING
    assert venue.account_type == AccountType.MARGIN
    assert venue.liquidation_enabled


def test_crypto_perp_buy_and_hold_pays_no_funding_and_only_the_entry_fee() -> None:
    assert asset_class("crypto_perp").buy_and_hold == BuyAndHold(
        pays_carry=False, pays_entry_fee=True, pays_exit_fee=False
    )
