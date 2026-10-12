from collections.abc import Mapping
from decimal import Decimal
from typing import Any, override

from sbt2.core.assets.base import MarginConvention, MarginModel, QuoteJob
from sbt2.core.assets.option_margin import ContractHolding, MarginRates
from sbt2.core.assets.option_margin_market import OptionMarket
from sbt2.data import Catalog


class OptionMargin(MarginConvention):
    """sbt2 margins an option as Deribit's standard margin does; its ``margin``
    setting holds the rates."""

    @override
    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        rates = MarginRates.from_table(venue.get("margin", {}))
        return {
            **venue,
            "margin": {
                "base_rate": f"{rates.base_rate:f}",
                "floor_rate": f"{rates.floor_rate:f}",
                "maintenance_rate": f"{rates.maintenance_rate:f}",
            },
        }

    @override
    def model(self, job: QuoteJob) -> MarginModel:
        rates = MarginRates.from_table(job.venue["margin"])
        return OptionMarginModel(rates, OptionMarket(Catalog(job.catalog), job.window))


class OptionMarginModel(MarginModel):
    def __init__(self, rates: MarginRates, market: OptionMarket) -> None:
        self._rates = rates
        self._market = market

    @override
    def initial(self, instrument: Any, quantity: Decimal, ts: int) -> Decimal:
        quote = self._market.quote(instrument, ts)
        return self._rates.initial_margin(ContractHolding(instrument, quantity), quote)

    @override
    def value(self, instrument: Any, quantity: Decimal, ts: int) -> Decimal:
        mark = self._market.quote(instrument, ts).mark
        return quantity * Decimal(str(instrument.multiplier)) * mark
