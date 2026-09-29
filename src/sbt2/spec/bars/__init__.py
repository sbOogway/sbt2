from sbt2.spec.bars.candles import CandleBarError, CandleBars
from sbt2.spec.bars.source import BarSource
from sbt2.spec.bars.trades import TradeBars
from sbt2.spec.errors import SpecError

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


__all__ = [
    "BarSource",
    "CandleBarError",
    "UnknownBarSourceError",
    "bar_source",
]
