from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from nautilus_trader.model import AssetClass, InstrumentClass, MarkPriceUpdate
from nautilus_trader.portfolio import PortfolioConfig

from sbt2.core.assets.calendars import Calendar
from sbt2.core.assets.conventions.buy_and_hold import BuyAndHoldConvention
from sbt2.core.assets.conventions.carry import Carry
from sbt2.core.assets.conventions.chain import ChainConvention, NoChain
from sbt2.core.assets.conventions.equity import EquityConvention, NativeEquity
from sbt2.core.assets.conventions.margin import MarginConvention, NoMargin
from sbt2.core.assets.conventions.quotes import NoQuotes, QuoteConvention
from sbt2.core.assets.conventions.settlement import NoSettlement, SettlementConvention


@dataclass(frozen=True)
class AssetProfile:
    """What sbt2 needs to know about one nautilus asset class and instrument class."""

    asset_class: AssetClass
    instrument_class: InstrumentClass
    calendar: Calendar
    days_per_year: int
    carry: Carry
    venue_defaults: Mapping[str, Any]
    reference_prices: tuple[type, ...]
    valuation_price: type
    buy_and_hold: BuyAndHoldConvention
    equity: EquityConvention = field(default_factory=NativeEquity)
    quotes: QuoteConvention = field(default_factory=NoQuotes)
    settlement: SettlementConvention = field(default_factory=NoSettlement)
    margin: MarginConvention = field(default_factory=NoMargin)
    chain: ChainConvention = field(default_factory=NoChain)

    def covers(self, instrument: Any) -> bool:
        return (
            instrument.asset_class == self.asset_class
            and instrument.instrument_class == self.instrument_class
        )

    def portfolio_config(self, snapshot_interval_ms: int) -> PortfolioConfig:
        return PortfolioConfig(
            use_mark_prices=self.valuation_price is MarkPriceUpdate,
            snapshot_interval_ms=snapshot_interval_ms,
        )
