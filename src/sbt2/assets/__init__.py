from sbt2.assets.base import AssetClass, BuyAndHold, Calendar, Carry
from sbt2.assets.crypto_perp import CRYPTO_PERP

__all__ = [
    "AssetClass",
    "BuyAndHold",
    "Calendar",
    "Carry",
    "UnknownAssetClassError",
    "asset_class",
]

_ASSET_CLASSES = {each.name: each for each in (CRYPTO_PERP,)}


class UnknownAssetClassError(LookupError):
    pass


def asset_class(name: str) -> AssetClass:
    try:
        return _ASSET_CLASSES[name]
    except KeyError:
        known = ", ".join(sorted(_ASSET_CLASSES))
        raise UnknownAssetClassError(
            f"unknown asset class {name!r}; known: {known}"
        ) from None
