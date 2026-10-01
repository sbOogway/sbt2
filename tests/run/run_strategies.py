from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import override

from nautilus_trader.model import Bar, BarSpecification, OrderSide, Quantity

from sbt2.core.strategy import NoParams, Strategy

HOURLY_BARS = BarSpecification.from_str("1-HOUR-LAST")


@dataclass(frozen=True)
class HoldParams:
    hold_bars: int = 20


class BuyThenSell(Strategy[HoldParams]):
    """Buys 1 BTC on the first bar after warm-up and sells it ``hold_bars`` later."""

    Params = HoldParams

    @classmethod
    @override
    def warmup(cls, params: HoldParams) -> timedelta:
        return timedelta(hours=2)

    @classmethod
    @override
    def inputs(cls, params: HoldParams) -> Sequence[BarSpecification]:
        return (HOURLY_BARS,)

    def on_start(self) -> None:
        super().on_start()
        self.bars = 0

    def on_bar(self, bar: Bar) -> None:
        if self.warming_up:
            return
        self.bars += 1
        side = {1: OrderSide.BUY, 1 + self.params.hold_bars: OrderSide.SELL}.get(
            self.bars
        )
        if side is not None:
            order = self.order_factory.market(
                bar.bar_type.instrument_id, side, Quantity.from_str("1.000")
            )
            self.submit_order(order)


class BuyThenReverse(Strategy[HoldParams]):
    """Buys 1 BTC on the first bar after warm-up and sells 2 ``hold_bars`` later."""

    Params = HoldParams

    @classmethod
    @override
    def warmup(cls, params: HoldParams) -> timedelta:
        return timedelta(hours=2)

    @classmethod
    @override
    def inputs(cls, params: HoldParams) -> Sequence[BarSpecification]:
        return (HOURLY_BARS,)

    def on_start(self) -> None:
        super().on_start()
        self.bars = 0

    def on_bar(self, bar: Bar) -> None:
        if self.warming_up:
            return
        self.bars += 1
        order = {
            1: (OrderSide.BUY, "1.000"),
            1 + self.params.hold_bars: (OrderSide.SELL, "2.000"),
        }.get(self.bars)
        if order is not None:
            side, quantity = order
            self.submit_order(
                self.order_factory.market(
                    bar.bar_type.instrument_id, side, Quantity.from_str(quantity)
                )
            )


class FailOnBar(Strategy[NoParams]):
    @classmethod
    @override
    def inputs(cls, params: NoParams) -> Sequence[BarSpecification]:
        return (HOURLY_BARS,)

    @override
    def on_bar(self, bar: Bar) -> None:
        raise RuntimeError("strategy blew up")


class HoldOnQuoteBars(Strategy[NoParams]):
    @classmethod
    @override
    def inputs(cls, params: NoParams) -> Sequence[BarSpecification]:
        return (BarSpecification.from_str("1-HOUR-BID"),)
