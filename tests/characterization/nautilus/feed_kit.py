from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, override

from kit import INSTRUMENT_ID, START, run_engine
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    BarType,
    OrderFilled,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)
from nautilus_trader.trading import Strategy

MINUTE = 60_000_000_000
BAR_TYPE = BarType.from_str(f"{INSTRUMENT_ID}-1-MINUTE-LAST-EXTERNAL")
# A bar spreads its volume evenly over its open, high, low and close.
BAR_PRICE_POINTS = 4


@dataclass(frozen=True)
class PricePath:
    closes: Sequence[str]
    size_per_price: str = "10.000"


def minute(step: int) -> int:
    return START + step * MINUTE


class Feed(ABC):
    @abstractmethod
    def data(self, path: PricePath) -> list[Any]: ...

    @abstractmethod
    def subscribe(self, strategy: Strategy) -> None: ...


class BarFeed(Feed):
    def data(self, path: PricePath) -> list[Any]:
        return bars(path)

    def subscribe(self, strategy: Strategy) -> None:
        strategy.subscribe_bars(BAR_TYPE)


class TradeFeed(Feed):
    def data(self, path: PricePath) -> list[Any]:
        return trades(path)

    def subscribe(self, strategy: Strategy) -> None:
        strategy.subscribe_trades(INSTRUMENT_ID)


def bars(path: PricePath) -> list[Bar]:
    volume = Quantity.from_str(str(Decimal(path.size_per_price) * BAR_PRICE_POINTS))
    opens = [path.closes[0], *path.closes[:-1]]
    return [
        Bar(
            BAR_TYPE,
            Price.from_str(open_),
            Price.from_str(max(open_, close, key=Decimal)),
            Price.from_str(min(open_, close, key=Decimal)),
            Price.from_str(close),
            volume,
            minute(step),
            minute(step),
        )
        for step, (open_, close) in enumerate(zip(opens, path.closes, strict=True))
    ]


# The venue matches a trade only against the side of the book its aggressor
# hit, so a falling tape has to be sold into to reach orders below the market.
def aggressor(previous: str, price: str) -> AggressorSide:
    if Decimal(price) < Decimal(previous):
        return AggressorSide.SELL
    return AggressorSide.BUY


def trades(path: PricePath) -> list[TradeTick]:
    previous = [path.closes[0], *path.closes[:-1]]
    return [
        TradeTick(
            INSTRUMENT_ID,
            Price.from_str(price),
            Quantity.from_str(path.size_per_price),
            aggressor(before, price),
            TradeId(str(step)),
            minute(step),
            minute(step),
        )
        for step, (before, price) in enumerate(zip(previous, path.closes, strict=True))
    ]


FEEDS: dict[str, Feed] = {"bars": BarFeed(), "trades": TradeFeed()}


class StepStrategy(Strategy):
    feed: Feed

    def on_start(self) -> None:
        self.step = 0
        self.feed.subscribe(self)

    @override
    def on_bar(self, bar: Bar) -> None:
        self.advance()

    @override
    def on_trade(self, trade: TradeTick) -> None:
        self.advance()

    def advance(self) -> None:
        self.on_step(self.step)
        self.step += 1

    def on_step(self, step: int) -> None:
        pass


def run_on_feed(strategy: StepStrategy, feed: str, path: PricePath) -> BacktestEngine:
    strategy.feed = FEEDS[feed]
    return run_engine(strategy.feed.data(path), strategy)


def fills(order: Any) -> list[tuple[int, str, str]]:
    return [
        (event.ts_event, str(event.last_px), str(event.last_qty))
        for event in order.events()
        if isinstance(event, OrderFilled)
    ]
