from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar, override

from nautilus_trader.model import (
    Bar,
    BarSpecification,
    OrderDenied,
    OrderRejected,
    OrderSide,
    Quantity,
)

from sbt2.core.strategy import Strategy

HOURLY_BARS = BarSpecification.from_str("1-HOUR-LAST")


@dataclass(frozen=True)
class SpotParams:
    buy: str = "0.500"
    sell: str = "0.500"
    hold_bars: int = 20


class BuyThenSellCoins(Strategy[SpotParams]):
    """Buys ``buy`` coins at the market on the first bar after warm-up and sells
    ``sell`` coins ``hold_bars`` later; notes why an order was refused."""

    Params = SpotParams
    refused: ClassVar[list[str]] = []

    @classmethod
    @override
    def warmup(cls, params: SpotParams) -> timedelta:
        return timedelta(hours=2)

    @classmethod
    @override
    def inputs(cls, params: SpotParams) -> tuple[BarSpecification, ...]:
        return (HOURLY_BARS,)

    def on_start(self) -> None:
        super().on_start()
        self.bars = 0

    def on_bar(self, bar: Bar) -> None:
        if self.warming_up:
            return
        self.bars += 1
        order = {
            1: (OrderSide.BUY, self.params.buy),
            1 + self.params.hold_bars: (OrderSide.SELL, self.params.sell),
        }.get(self.bars)
        if order is not None:
            side, coins = order
            self.submit_order(
                self.order_factory.market(
                    bar.bar_type.instrument_id, side, Quantity.from_str(coins)
                )
            )

    @override
    def on_order_denied(self, event: OrderDenied) -> None:
        super().on_order_denied(event)
        self.refused.append(str(event.reason))

    @override
    def on_order_rejected(self, event: OrderRejected) -> None:
        super().on_order_rejected(event)
        self.refused.append(str(event.reason))
