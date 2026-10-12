from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import ClassVar, override

from nautilus_trader.model import (
    Bar,
    BarSpecification,
    MarketOrder,
    OrderFilled,
    OrderSide,
    Quantity,
)

from sbt2.core.strategy import NoParams, Strategy

HOURLY_BARS = BarSpecification.from_str("1-HOUR-LAST")
HOURLY_MID_BARS = BarSpecification.from_str("1-HOUR-MID")


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


class BuyOneOption(Strategy[NoParams]):
    """Buys one option contract on the first bar after warm-up."""

    side = OrderSide.BUY
    quantity = "1.0"

    @classmethod
    @override
    def warmup(cls, params: NoParams) -> timedelta:
        return timedelta(hours=2)

    @classmethod
    @override
    def inputs(cls, params: NoParams) -> Sequence[BarSpecification]:
        return (HOURLY_MID_BARS,)

    def on_start(self) -> None:
        super().on_start()
        self.ordered = False

    def on_bar(self, bar: Bar) -> None:
        if self.warming_up or self.ordered:
            return
        self.ordered = True
        self.place(
            self.order_factory.market(
                bar.bar_type.instrument_id, self.side, Quantity.from_str(self.quantity)
            )
        )

    def place(self, order: MarketOrder) -> None:
        self.submit_order(order)


class SellOneOption(BuyOneOption):
    """Sells one option contract on the first bar after warm-up."""

    side = OrderSide.SELL


class SellTenOptions(SellOneOption):
    """Sells ten option contracts, more than 1 BTC of capital can margin."""

    quantity = "10.0"
    refused: ClassVar[list[tuple[str, str]]] = []

    @override
    def on_margin_refused(self, order: MarketOrder, reason: str) -> None:
        self.refused.append((str(order.instrument_id), reason))


class SellTenOptionsAsAList(SellTenOptions):
    """Sends its orders as a list."""

    @override
    def place(self, order: MarketOrder) -> None:
        self.submit_order_list([order])


class ReadOrderMargin(SellOneOption):
    """Notes the margin of its order, in the coin, with the time it asked."""

    asked: ClassVar[list[tuple[int, Decimal]]] = []

    @override
    def place(self, order: MarketOrder) -> None:
        self.asked.append((self.clock.timestamp_ns(), self.margin_of_order(order)))
        super().place(order)


class ReadPositionMargin(SellOneOption):
    """Notes the margin of its open positions on each bar."""

    read: ClassVar[list[tuple[int, dict[str, Decimal]]]] = []

    @override
    def on_bar(self, bar: Bar) -> None:
        super().on_bar(bar)
        margins = {str(k): v for k, v in self.margin_of_positions().items()}
        if margins:
            self.read.append((self.clock.timestamp_ns(), margins))


class ListenToSettlement(BuyOneOption):
    """Buys one option contract and notes the settlements it hears."""

    settled: ClassVar[list[tuple[str, float, float]]] = []

    @override
    def on_settlement(self, fill: OrderFilled) -> None:
        self.settled.append(
            (str(fill.instrument_id), float(fill.last_px), float(fill.last_qty))
        )


class ListenToFills(ListenToSettlement):
    """Also overrides ``on_order_filled``, without calling the base class."""

    filled: ClassVar[list[str]] = []

    @override
    def on_order_filled(self, event: OrderFilled) -> None:
        self.filled.append(str(event.order_side))


class ActOnSchedule(Strategy[NoParams]):
    """Declares no bars and notes the time of each tick of an hourly schedule."""

    ticks: ClassVar[list[datetime]] = []

    @classmethod
    @override
    def inputs(cls, params: NoParams) -> Sequence[BarSpecification]:
        return ()

    @classmethod
    @override
    def schedule(cls, params: NoParams) -> timedelta | None:
        return timedelta(hours=1)

    @override
    def on_schedule(self, now: datetime) -> None:
        self.ticks.append(now)

    @override
    def on_bar(self, bar: Bar) -> None:
        raise AssertionError("a chain strategy without bars heard a bar")


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
