from collections.abc import Sequence
from pathlib import Path

from nautilus_trader.backtest import BacktestDataConfig
from nautilus_trader.model import BarSpecification, PriceType, QuoteTick, TradeTick

from sbt2.core.assets import QuoteJob
from sbt2.core.spec.bars.source import BarSource


class TradeBars(BarSource):
    """Bars built from trades on LAST prices, and from quotes on the others."""

    name = "trades"
    aggregated_from = None

    def data_types(self, inputs: Sequence[BarSpecification]) -> set[type]:
        return {
            TradeTick if spec.price_type == PriceType.LAST else QuoteTick
            for spec in inputs
        }

    def write_fills(self, job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
        """Orders fill on the trades and quotes the run streams."""
        del job, folder
        return []
