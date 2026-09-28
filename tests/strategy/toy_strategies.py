from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from nautilus_trader.model import Bar, OrderSide, Quantity

from sbt2.strategy import Bars, Input, NoParams, Strategy

MINUTE_BARS = Bars("1-MINUTE-LAST")


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
    def inputs(cls, params: StepParams) -> Sequence[Input]:
        return (MINUTE_BARS,)

    def on_bar(self, bar: Bar) -> None:
        quantity = Quantity.from_str(str(self.params.step))
        order = self.order_factory.market(
            bar.bar_type.instrument_id, OrderSide.BUY, quantity
        )
        self.submit_order(order)


class CountWarmupBars(Strategy[NoParams]):
    def on_start(self) -> None:
        super().on_start()
        self.warmup_bars = 0
        self.trading_bars = 0

    @classmethod
    def inputs(cls, params: NoParams) -> Sequence[Input]:
        return (MINUTE_BARS,)

    def on_bar(self, bar: Bar) -> None:
        if self.warming_up:
            self.warmup_bars += 1
        else:
            self.trading_bars += 1


class NotAStrategy:
    pass
