from collections.abc import Sequence

from nautilus_trader.model import BarSpecification, PriceType, QuoteTick, TradeTick

from sbt2.spec.bars.source import BarSource


class TradeBars(BarSource):
    """Bars built from trades on LAST prices, and from quotes on the others."""

    name = "trades"
    aggregated_from = None

    def data_types(self, inputs: Sequence[BarSpecification]) -> set[type]:
        return {
            TradeTick if spec.price_type == PriceType.LAST else QuoteTick
            for spec in inputs
        }
