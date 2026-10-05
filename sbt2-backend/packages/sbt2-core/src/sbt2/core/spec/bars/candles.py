from collections.abc import Sequence
from datetime import timedelta

from nautilus_trader.model import Bar, BarSpecification, PriceType

from sbt2.core.spec.bars.source import BarSource
from sbt2.core.spec.errors import SpecError
from sbt2.data import CANDLES

_MINUTE = timedelta(minutes=1)


class CandleBarError(SpecError):
    """A declared bar that 1-minute candles cannot build."""


class CandleBars(BarSource):
    """Bars built from a source's 1-minute candles."""

    name = "candles"
    aggregated_from = CANDLES

    def data_types(self, inputs: Sequence[BarSpecification]) -> set[type]:
        for spec in inputs:
            _check_candle_built(spec)
        return {Bar}


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
