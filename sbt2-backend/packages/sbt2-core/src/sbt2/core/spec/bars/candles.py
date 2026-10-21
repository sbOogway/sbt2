from collections.abc import Sequence
from datetime import timedelta
from enum import StrEnum
from pathlib import Path

from nautilus_trader.backtest import BacktestDataConfig
from nautilus_trader.model import Bar, BarSpecification, PriceType

from sbt2.core.assets import QuoteJob
from sbt2.core.spec.bars.opens import write_opens
from sbt2.core.spec.bars.source import BarSource
from sbt2.core.spec.errors import SpecError
from sbt2.data import CANDLES

_MINUTE = timedelta(minutes=1)


class CandleBarError(SpecError):
    """A declared bar that 1-minute candles cannot build."""


class Fills(StrEnum):
    """Where a candle run fills an order sent on a bar's close: at the next
    candle's open, or at that close."""

    NEXT_OPEN = "next_open"
    CLOSE = "close"


class CandleBars(BarSource):
    """Bars built from a source's 1-minute candles."""

    name = "candles"
    aggregated_from = CANDLES

    def data_types(self, inputs: Sequence[BarSpecification]) -> set[type]:
        for spec in inputs:
            _check_candle_built(spec)
        return {Bar}

    def write_fills(self, job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
        """With fills at the next open, a trade at the open of each candle."""
        if job.venue["fills"] != Fills.NEXT_OPEN:
            return []
        return write_opens(job, folder)


def _check_candle_built(spec: BarSpecification) -> None:
    buildable = (
        spec.is_time_aggregated()
        and spec.timedelta % _MINUTE == timedelta(0)
        and spec.price_type == PriceType.LAST
    )
    if not buildable:
        raise CandleBarError(
            f"1-minute candles cannot build {spec} bars; they build time bars "
            "of whole minutes on LAST prices"
        )
