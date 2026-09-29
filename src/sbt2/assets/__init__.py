import copyreg
from collections.abc import Callable
from typing import Any

from nautilus_trader.model import AccountType, AssetClass, InstrumentClass, OmsType

from sbt2.assets.base import AssetProfile, Calendar, Carry
from sbt2.assets.crypto_perp import CRYPTO_PERP

__all__ = [
    "AssetProfile",
    "Calendar",
    "Carry",
    "UnknownAssetClassError",
    "asset_profile",
]

_PROFILES = {(each.asset_class, each.instrument_class): each for each in (CRYPTO_PERP,)}


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


def _by_name(value: Any) -> tuple[Callable[..., Any], tuple[type, str]]:
    """Nautilus's enums don't pickle; they come back by their name."""
    return getattr, (type(value), value.name)


def _by_classes(
    profile: AssetProfile,
) -> tuple[Callable[..., AssetProfile], tuple[AssetClass, InstrumentClass]]:
    return asset_profile, (profile.asset_class, profile.instrument_class)


for _enum in (AssetClass, InstrumentClass, OmsType, AccountType):
    copyreg.pickle(_enum, _by_name)
copyreg.pickle(AssetProfile, _by_classes)
