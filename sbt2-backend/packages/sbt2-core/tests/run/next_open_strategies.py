from dataclasses import dataclass
from typing import override

from nautilus_trader.model import Bar, BarSpecification, OrderSide, Quantity

from sbt2.core.strategy import Strategy

MINUTE_BARS = BarSpecification.from_str("1-MINUTE-LAST")


@dataclass(frozen=True)
class TradeParams:
    """Open ``quantity`` on ``side`` on the close of bar ``entry`` and, when
    ``exit`` is set, close it on the close of bar ``exit``; bars count from 1 at
    the start."""

    side: str = "BUY"
    quantity: str = "1.000"
    entry: int = 1
    exit: int = 0


class TradeOnClose(Strategy[TradeParams]):
    """Sends market orders on the close of 1-minute bars."""

    Params = TradeParams

    @classmethod
    @override
    def inputs(cls, params: TradeParams) -> tuple[BarSpecification, ...]:
        return (MINUTE_BARS,)

    def on_start(self) -> None:
        super().on_start()
        self.bars = 0

    def on_bar(self, bar: Bar) -> None:
        super().on_bar(bar)
        if self.warming_up:
            return
        self.bars += 1
        side = {"BUY": OrderSide.BUY, "SELL": OrderSide.SELL}[self.params.side]
        if self.bars == self.params.entry:
            self.send(side)
        elif self.bars == self.params.exit:
            self.send(OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY)

    def send(self, side: OrderSide) -> None:
        order = self.order_factory.market(
            self.instrument_ids[0], side, Quantity.from_str(self.params.quantity)
        )
        self.submit_order(order)


class TradeOnAlert(TradeOnClose):
    """Sends each order from a clock alert 1 ns after the bar's close."""

    @override
    def send(self, side: OrderSide) -> None:
        self.clock.set_time_alert_ns(
            f"send-{self.bars}",
            self.clock.timestamp_ns() + 1,
            callback=lambda _: super(TradeOnAlert, self).send(side),
        )
