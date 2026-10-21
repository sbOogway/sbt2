from nautilus_trader.model import AssetClass, InstrumentClass

from sbt2.core.assets.future.profile import CRYPTO_FUTURE
from sbt2.core.assets.option.profile import CRYPTO_OPTION
from sbt2.core.assets.perp.profile import CRYPTO_PERP
from sbt2.core.assets.profile import AssetProfile
from sbt2.core.assets.spot.profile import CRYPTO_SPOT

_PROFILES = {
    (each.asset_class, each.instrument_class): each
    for each in (CRYPTO_PERP, CRYPTO_OPTION, CRYPTO_FUTURE, CRYPTO_SPOT)
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
