from sbt2.core.spec.bars.candles import CandleBarError, CandleBars, Fills
from sbt2.core.spec.bars.source import BarSource
from sbt2.core.spec.bars.trades import TradeBars
from sbt2.core.spec.errors import SpecError

_BAR_SOURCES: tuple[BarSource, ...] = (TradeBars(), CandleBars())


class UnknownBarSourceError(SpecError):
    pass


def bar_source(name: str) -> BarSource:
    """The bar source a spec file's ``bars`` names."""
    for each in _BAR_SOURCES:
        if each.name == name:
            return each
    known = ", ".join(each.name for each in _BAR_SOURCES)
    raise UnknownBarSourceError(f"bars {name!r} is not one of {known}")


def aggregating(aggregated_from: str | None) -> BarSource:
    """The bar source whose bars are aggregated from ``aggregated_from``."""
    [found] = [each for each in _BAR_SOURCES if each.aggregated_from == aggregated_from]
    return found


__all__ = [
    "BarSource",
    "CandleBarError",
    "Fills",
    "UnknownBarSourceError",
    "aggregating",
    "bar_source",
]
