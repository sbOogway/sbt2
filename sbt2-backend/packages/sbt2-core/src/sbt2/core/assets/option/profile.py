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
from sbt2.core.assets.option.chain.convention import OptionChain
from sbt2.core.assets.option.equity import PremiumEquity
from sbt2.core.assets.option.margin.convention import OptionMargin
from sbt2.core.assets.option.quotes.convention import OptionQuotes
from sbt2.core.assets.option.settlement.convention import OptionSettlement
from sbt2.core.assets.profile import AssetProfile

CRYPTO_OPTION = AssetProfile(
    asset_class=AssetClass.CRYPTOCURRENCY,
    instrument_class=InstrumentClass.OPTION,
    calendar=AlwaysOpen(),
    days_per_year=365,
    carry=Carry(data_types=()),
    venue_defaults=MappingProxyType(
        {
            "oms_type": OmsType.NETTING,
            "account_type": AccountType.MARGIN,
            "liquidation_enabled": False,
        }
    ),
    reference_prices=(MarkPriceUpdate,),
    valuation_price=MarkPriceUpdate,
    equity=PremiumEquity(),
    margin=OptionMargin(),
    quotes=OptionQuotes(),
    settlement=OptionSettlement(),
    chain=OptionChain(),
    buy_and_hold=NoBuyAndHold(reason="an option expires, so it cannot be held"),
)
