from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from nautilus_trader.model import Bar, BarSpecification, BarType, OrderSide, Quantity

from sbt2.strategy import NoParams, Strategy

MINUTE_BARS = BarSpecification.from_str("1-MINUTE-LAST")


@dataclass(frozen=True)
class StepParams:
    step: Decimal = Decimal("0.100")
    lookback: int = 3


class BuyEveryBar(Strategy[StepParams]):
    """Buys ``step`` on every bar, warm-up included."""

    Params = StepParams

    @classmethod
    def warmup(cls, params: StepParams) -> timedelta:
        return timedelta(minutes=params.lookback)

    @classmethod
    def inputs(cls, params: StepParams) -> Sequence[BarSpecification]:
        return (MINUTE_BARS,)

    def on_bar(self, bar: Bar) -> None:
        quantity = Quantity.from_str(str(self.params.step))
        order = self.order_factory.market(
            bar.bar_type.instrument_id, OrderSide.BUY, quantity
        )
        self.submit_order(order)


class BuyOnce(Strategy[NoParams]):
    """Buys 1 on the first bar after warm-up and holds it."""

    @classmethod
    def inputs(cls, params: NoParams) -> Sequence[BarSpecification]:
        return (MINUTE_BARS,)

    def on_start(self) -> None:
        super().on_start()
        self.bought = False

    def on_bar(self, bar: Bar) -> None:
        if self.warming_up or self.bought:
            return
        self.bought = True
        order = self.order_factory.market(
            bar.bar_type.instrument_id, OrderSide.BUY, Quantity.from_str("1.000")
        )
        self.submit_order(order)


class CountWarmupBars(Strategy[NoParams]):
    def on_start(self) -> None:
        super().on_start()
        self.warmup_bars = 0
        self.trading_bars = 0

    @classmethod
    def inputs(cls, params: NoParams) -> Sequence[BarSpecification]:
        return (MINUTE_BARS,)

    def on_bar(self, bar: Bar) -> None:
        if self.warming_up:
            self.warmup_bars += 1
        else:
            self.trading_bars += 1


class NotAStrategy:
    pass


class FailOnSecondBar(Strategy[NoParams]):
    def on_start(self) -> None:
        super().on_start()
        self.bars = 0

    @classmethod
    def inputs(cls, params: NoParams) -> Sequence[BarSpecification]:
        return (MINUTE_BARS,)

    def on_bar(self, bar: Bar) -> None:
        self.bars += 1
        if self.bars == 2:
            raise ValueError(f"failed on bar {self.bars}")


@dataclass(frozen=True)
class BarParams:
    bar: str = "1-HOUR-LAST"


class RecordBars(Strategy[BarParams]):
    """Keeps every bar it gets, and every bar type it subscribes to."""

    Params = BarParams

    @classmethod
    def inputs(cls, params: BarParams) -> Sequence[BarSpecification]:
        return (BarSpecification.from_str(params.bar),)

    def on_start(self) -> None:
        self.bars: list[Bar] = []
        self.subscribed: list[BarType] = []
        super().on_start()

    def subscribe_bars(self, bar_type: BarType, *args: Any, **kwargs: Any) -> None:
        self.subscribed.append(bar_type)
        super().subscribe_bars(bar_type, *args, **kwargs)

    def on_bar(self, bar: Bar) -> None:
        self.bars.append(bar)
