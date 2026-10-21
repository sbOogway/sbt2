from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any, override

from nautilus_trader.backtest import BacktestDataConfig
from nautilus_trader.model import (
    BarSpecification,
    NautilusDataType,
    OptionGreeks,
    PriceType,
    QuoteTick,
    TradeTick,
)

from sbt2.core.assets.conventions.quotes import QuoteConvention, QuoteJob
from sbt2.core.assets.option.quotes.catalog import write_quotes
from sbt2.core.assets.option.quotes.quotes import QuoteSettings


class OptionQuotes(QuoteConvention):
    """The quotes of an option venue are made from the marks, the IV and the
    index; its ``quotes`` setting holds the spread model."""

    @override
    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        return {**venue, "quotes": asdict(self.settings(venue))}

    def settings(self, venue: Mapping[str, Any]) -> QuoteSettings:
        try:
            return QuoteSettings(**venue.get("quotes", {}))
        except TypeError as error:
            raise ValueError(f"the quotes setting is invalid: {error}") from error

    @override
    def unmakeable(self, inputs: Sequence[BarSpecification]) -> list[BarSpecification]:
        return [each for each in inputs if each.price_type == PriceType.LAST]

    @override
    def source_types(self, kinds: set[type], venue: Mapping[str, Any]) -> set[type]:
        """Quotes and trades are not read from the catalog: the quotes are made
        from the IV records, and trades must not reach the venue's book."""
        del venue
        return (kinds - {QuoteTick, TradeTick}) | {OptionGreeks}

    @override
    def write(self, job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
        quoted = write_quotes(job, self.settings(job.venue), folder)
        start, end = job.window
        return [
            BacktestDataConfig(
                catalog_path=str(folder),
                data_type=NautilusDataType.QuoteTick,
                instrument_ids=quoted,
                start_time=start,
                end_time=end,
            )
        ]
