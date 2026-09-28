from types import MappingProxyType

from nautilus_trader.model import (
    AccountType,
    AssetClass,
    CryptoPerpetual,
    FundingRateUpdate,
    InstrumentClass,
    MarkPriceUpdate,
    OmsType,
)

from sbt2.assets.base import AssetProfile, BuyAndHold, Carry
from sbt2.assets.calendars import AlwaysOpen

CRYPTO_PERP = AssetProfile(
    asset_class=AssetClass.CRYPTOCURRENCY,
    instrument_class=InstrumentClass.SWAP,
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
