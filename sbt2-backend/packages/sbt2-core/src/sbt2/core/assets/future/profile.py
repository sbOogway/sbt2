from types import MappingProxyType

from nautilus_trader.model import (
    AccountType,
    AssetClass,
    InstrumentClass,
    MarkPriceUpdate,
    OmsType,
)

from sbt2.core.assets.calendars import AlwaysOpen
from sbt2.core.assets.conventions.buy_and_hold import NoBuyAndHold
from sbt2.core.assets.conventions.carry import Carry
from sbt2.core.assets.future.quotes import FutureQuotes
from sbt2.core.assets.profile import AssetProfile

CRYPTO_FUTURE = AssetProfile(
    asset_class=AssetClass.CRYPTOCURRENCY,
    instrument_class=InstrumentClass.FUTURE,
    calendar=AlwaysOpen(),
    days_per_year=365,
    carry=Carry(data_types=()),
    quotes=FutureQuotes(),
    venue_defaults=MappingProxyType(
        {
            "oms_type": OmsType.NETTING,
            "account_type": AccountType.MARGIN,
            "liquidation_enabled": False,
        }
    ),
    reference_prices=(MarkPriceUpdate,),
    valuation_price=MarkPriceUpdate,
    buy_and_hold=NoBuyAndHold(reason="a future expires, so it cannot be held"),
)
