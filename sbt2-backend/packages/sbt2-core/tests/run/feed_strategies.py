from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import override

from nautilus_trader.model import Bar, BarSpecification, InstrumentId

from sbt2.core.strategy import Anchor, MultiVenueVwap, Strategy

MINUTE_BARS = BarSpecification.from_str("1-MINUTE-LAST")


@dataclass(frozen=True)
class FeedParams:
    first: str = "BTCUSDT-PERP.BINANCE"
    second: str = "BTC-USDT-SWAP.OKX"


class Heard:
    """What the strategies below saw, for the test that runs them in-process."""

    def __init__(self) -> None:
        self.bars: Counter[str] = Counter()
        self.vwaps: dict[int, float | None] = {}

    def clear(self) -> None:
        self.bars.clear()
        self.vwaps.clear()


HEARD = Heard()


class Listener(Strategy[FeedParams]):
    """Trades nothing; counts the bars it hears by bar type."""

    Params = FeedParams

    @classmethod
    @override
    def inputs(cls, params: FeedParams) -> Sequence[BarSpecification]:
        return (MINUTE_BARS,)

    @classmethod
    @override
    def feeds(cls, params: FeedParams) -> Sequence[InstrumentId]:
        return (
            InstrumentId.from_str(params.first),
            InstrumentId.from_str(params.second),
        )

    def on_bar(self, bar: Bar) -> None:
        HEARD.bars[str(bar.bar_type.instrument_id)] += 1


class VwapListener(Listener):
    """Feeds the bars of its feeds to a VWAP and records it after each bar."""

    def on_start(self) -> None:
        super().on_start()
        feeds = self.feeds(self.params)
        instruments = [self.cache.instrument(each) for each in feeds]
        self.vwap = MultiVenueVwap(
            [each for each in instruments if each is not None], Anchor.SESSION
        )

    @override
    def on_bar(self, bar: Bar) -> None:
        if bar.bar_type.instrument_id in self.feeds(self.params):
            self.vwap.update(bar)
            HEARD.vwaps[bar.ts_event] = self.vwap.vwap


class Plain(Strategy[FeedParams]):
    """Declares no feeds."""

    Params = FeedParams

    @classmethod
    @override
    def inputs(cls, params: FeedParams) -> Sequence[BarSpecification]:
        return (MINUTE_BARS,)

    def on_bar(self, bar: Bar) -> None:
        HEARD.bars[str(bar.bar_type.instrument_id)] += 1
