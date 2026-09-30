from types import MappingProxyType

from nautilus_trader.model import (
    AccountType,
    AssetClass,
    FundingRateUpdate,
    InstrumentClass,
    MarkPriceUpdate,
    OmsType,
)

from sbt2.assets.base import AssetProfile, BuyAndHoldConvention, Carry
from sbt2.assets.calendars import AlwaysOpen

CRYPTO_PERP = AssetProfile(
    asset_class=AssetClass.CRYPTOCURRENCY,
    instrument_class=InstrumentClass.SWAP,
    calendar=AlwaysOpen(),
    days_per_year=365,
    carry=Carry(data_types=(FundingRateUpdate,)),
    venue_defaults=MappingProxyType(
        {
            "oms_type": OmsType.NETTING,
            "account_type": AccountType.MARGIN,
            "liquidation_enabled": False,
        }
    ),
    reference_prices=(MarkPriceUpdate,),
    valuation_price=MarkPriceUpdate,
    buy_and_hold=BuyAndHoldConvention(
        price=MarkPriceUpdate, carry=Carry(data_types=())
    ),
)
