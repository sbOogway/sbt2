from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import ClassVar, override

from nautilus_trader.model import (
    Bar,
    BarSpecification,
    OrderDenied,
    OrderFilled,
    OrderRejected,
    OrderSide,
    Price,
    Quantity,
)

from sbt2.core.strategy import Strategy

HOURLY_BARS = BarSpecification.from_str("1-HOUR-LAST")
LIMIT_STEP = Decimal(500)


@dataclass(frozen=True)
class TradeParams:
    side: str = "BUY"
    hold_bars: int = 20
    usd: int = 100_000


class _FirstBar(Strategy[TradeParams]):
    """Acts on the first hourly bar after warm-up."""

    Params = TradeParams

    @classmethod
    @override
    def warmup(cls, params: TradeParams) -> timedelta:
        return timedelta(hours=2)

    @classmethod
    @override
    def inputs(cls, params: TradeParams) -> tuple[BarSpecification, ...]:
        return (HOURLY_BARS,)

    def on_start(self) -> None:
        super().on_start()
        self.bars = 0

    def on_bar(self, bar: Bar) -> None:
        if self.warming_up:
            return
        self.bars += 1
        if self.bars == 1:
            self.open(bar)
        elif self.bars == 1 + self.params.hold_bars:
            self.close(bar)

    def open(self, bar: Bar) -> None:
        del bar

    def close(self, bar: Bar) -> None:
        del bar

    @property
    def side(self) -> OrderSide:
        return {"BUY": OrderSide.BUY, "SELL": OrderSide.SELL}[self.params.side]

    @property
    def usd(self) -> Quantity:
        return Quantity.from_int(self.params.usd)

    def market(self, bar: Bar, side: OrderSide) -> None:
        self.submit_order(
            self.order_factory.market(bar.bar_type.instrument_id, side, self.usd)
        )

    def limit(self, bar: Bar, side: OrderSide, price: Decimal) -> None:
        self.submit_order(
            self.order_factory.limit(
                bar.bar_type.instrument_id,
                side,
                self.usd,
                Price(float(price), bar.close.precision),
            )
        )


class TradeUsd(_FirstBar):
    """Trades ``usd`` of an inverse contract, once as maker and once as taker:
    a long buys at the market and sells at a limit ``LIMIT_STEP`` above the first
    close; a short sells at that limit and buys back at the market ``hold_bars``
    later."""

    @override
    def open(self, bar: Bar) -> None:
        above = Decimal(str(bar.close)) + LIMIT_STEP
        if self.side == OrderSide.BUY:
            self.market(bar, OrderSide.BUY)
            self.limit(bar, OrderSide.SELL, above)
        else:
            self.limit(bar, OrderSide.SELL, above)

    @override
    def close(self, bar: Bar) -> None:
        if self.side == OrderSide.SELL:
            self.market(bar, OrderSide.BUY)


class HoldUsdToExpiry(_FirstBar):
    """Opens ``usd`` of a contract at the market and keeps an order resting
    far from the market until the contract settles."""

    settled: ClassVar[list[tuple[str, float, float]]] = []

    @override
    def open(self, bar: Bar) -> None:
        self.market(bar, self.side)
        close = Decimal(str(bar.close))
        if self.side == OrderSide.BUY:
            self.limit(bar, OrderSide.SELL, close * 2)
        else:
            self.limit(bar, OrderSide.BUY, close / 2)

    @override
    def on_settlement(self, fill: OrderFilled) -> None:
        self.settled.append(
            (str(fill.instrument_id), float(fill.last_px), float(fill.last_qty))
        )


class OverReach(HoldUsdToExpiry):
    """Also sends, first, an order whose margin is more than the balance, and notes
    why it was refused."""

    refused: ClassVar[list[str]] = []

    @override
    def open(self, bar: Bar) -> None:
        self.submit_order(
            self.order_factory.market(
                bar.bar_type.instrument_id,
                self.side,
                Quantity.from_int(500 * self.params.usd),
            )
        )
        super().open(bar)

    @override
    def on_order_denied(self, event: OrderDenied) -> None:
        super().on_order_denied(event)
        self.refused.append(str(event.reason))

    @override
    def on_order_rejected(self, event: OrderRejected) -> None:
        super().on_order_rejected(event)
        self.refused.append(str(event.reason))
