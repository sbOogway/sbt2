from types import MappingProxyType

from nautilus_trader.model import (
    AccountType,
    AssetClass,
    InstrumentClass,
    MarkPriceUpdate,
    OmsType,
)

from sbt2.core.assets.base import AssetProfile, Carry, NoBuyAndHold
from sbt2.core.assets.calendars import AlwaysOpen
from sbt2.core.assets.option_margin_convention import OptionMargin
from sbt2.core.assets.option_quote_convention import OptionQuotes
from sbt2.core.assets.option_settlement_convention import OptionSettlement
from sbt2.core.assets.premium_equity import PremiumEquity

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
    buy_and_hold=NoBuyAndHold(reason="an option expires, so it cannot be held"),
)
