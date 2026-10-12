from nautilus_trader.model import AssetClass, InstrumentClass

from sbt2.core.assets.base import (
    AssetProfile,
    BuyAndHoldConvention,
    Calendar,
    Carry,
    MarginConvention,
    MarginModel,
    NoBuyAndHoldError,
    NoTakerRateError,
    QuoteConvention,
    QuoteJob,
)
from sbt2.core.assets.crypto_option import CRYPTO_OPTION
from sbt2.core.assets.crypto_perp import CRYPTO_PERP
from sbt2.core.assets.option_delivery import NoDeliveryPriceError
from sbt2.core.assets.option_margin import ContractHolding, MarginRates, OptionQuote
from sbt2.core.assets.option_margin_market import NoMarkError
from sbt2.core.assets.option_quote_catalog import NoQuotesError
from sbt2.core.assets.option_quotes import OptionHistory, QuoteSettings, quote_ticks
from sbt2.core.assets.option_settlement import DeliveryFee, settlement_price

__all__ = [
    "AssetProfile",
    "BuyAndHoldConvention",
    "Calendar",
    "Carry",
    "ContractHolding",
    "DeliveryFee",
    "MarginConvention",
    "MarginModel",
    "MarginRates",
    "NoBuyAndHoldError",
    "NoDeliveryPriceError",
    "NoMarkError",
    "NoQuotesError",
    "NoTakerRateError",
    "OptionHistory",
    "OptionQuote",
    "QuoteConvention",
    "QuoteJob",
    "QuoteSettings",
    "UnknownAssetClassError",
    "asset_profile",
    "quote_ticks",
    "settlement_price",
]

_PROFILES = {
    (each.asset_class, each.instrument_class): each
    for each in (CRYPTO_PERP, CRYPTO_OPTION)
}


class UnknownAssetClassError(LookupError):
    pass


def asset_profile(
    asset_class: AssetClass, instrument_class: InstrumentClass
) -> AssetProfile:
    try:
        return _PROFILES[(asset_class, instrument_class)]
    except KeyError:
        known = ", ".join(sorted(f"{a.name}/{i.name}" for a, i in _PROFILES))
        raise UnknownAssetClassError(
            f"no asset profile for {asset_class.name}/{instrument_class.name}; "
            f"known: {known}"
        ) from None
