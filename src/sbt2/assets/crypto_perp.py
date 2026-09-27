from types import MappingProxyType

from nautilus_trader.model import (
    AccountType,
    CryptoPerpetual,
    FundingRateUpdate,
    MarkPriceUpdate,
    OmsType,
)

from sbt2.assets.base import AssetClass, BuyAndHold, Carry
from sbt2.assets.calendars import AlwaysOpen

CRYPTO_PERP = AssetClass(
    name="crypto_perp",
    instrument_type=CryptoPerpetual,
    calendar=AlwaysOpen(),
    days_per_year=365,
    carry=Carry(name="funding", data_types=(FundingRateUpdate,)),
    venue_defaults=MappingProxyType(
        {
            "oms_type": OmsType.NETTING,
            "account_type": AccountType.MARGIN,
            "liquidation_enabled": True,
        }
    ),
    reference_prices=(MarkPriceUpdate,),
    valuation_price=MarkPriceUpdate,
    buy_and_hold=BuyAndHold(pays_carry=False, pays_entry_fee=True, pays_exit_fee=False),
)
