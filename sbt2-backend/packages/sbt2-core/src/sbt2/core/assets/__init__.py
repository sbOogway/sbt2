from nautilus_trader.model import AssetClass, InstrumentClass

from sbt2.core.assets.base import (
    AssetProfile,
    BuyAndHoldConvention,
    Calendar,
    Carry,
    NoBuyAndHoldError,
    NoTakerRateError,
)
from sbt2.core.assets.crypto_option import CRYPTO_OPTION
from sbt2.core.assets.crypto_perp import CRYPTO_PERP

__all__ = [
    "AssetProfile",
    "BuyAndHoldConvention",
    "Calendar",
    "Carry",
    "NoBuyAndHoldError",
    "NoTakerRateError",
    "UnknownAssetClassError",
    "asset_profile",
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
