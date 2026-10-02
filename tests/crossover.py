"""A copy of sbt2-strategies' moving-average cross, the sample strategy the core
tests run without depending on that package."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from nautilus_trader.indicators import SimpleMovingAverage
from nautilus_trader.model import (
    Bar,
    BarSpecification,
    InstrumentId,
    OrderSide,
    Quantity,
)

from sbt2.core.strategy import Strategy


@dataclass(frozen=True)
class CrossParams:
    fast: int = 10
    slow: int = 30
    bar: str = "1-HOUR-LAST"
    quantity: Decimal = Decimal("0.100")


class MovingAverageCross(Strategy[CrossParams]):
    """Long ``quantity`` while the fast average is above the slow one, short below.

    It reverses on every cross, so after warm-up it always holds a position.
    """

    Params = CrossParams

    @classmethod
    def warmup(cls, params: CrossParams) -> timedelta:
        return params.slow * _bar(params).timedelta

    @classmethod
    def inputs(cls, params: CrossParams) -> Sequence[BarSpecification]:
        return (_bar(params),)

    def on_start(self) -> None:
        super().on_start()
        self.averages: dict[str, tuple[SimpleMovingAverage, SimpleMovingAverage]] = {}
        for bar_type in self.bar_types():
            fast = SimpleMovingAverage(self.params.fast)
            slow = SimpleMovingAverage(self.params.slow)
            self.register_indicator_for_bars(bar_type, fast)
            self.register_indicator_for_bars(bar_type, slow)
            self.averages[str(bar_type)] = (fast, slow)

    def on_bar(self, bar: Bar) -> None:
        fast, slow = self.averages[str(bar.bar_type)]
        if not slow.initialized or fast.value == slow.value:
            return
        target = self.params.quantity
        self._trade_to(
            bar.bar_type.instrument_id, target if fast.value > slow.value else -target
        )

    def _trade_to(self, instrument_id: InstrumentId, target: Decimal) -> None:
        change = target - Decimal(self.portfolio.net_position(instrument_id))
        if change == 0:
            return
        side = OrderSide.BUY if change > 0 else OrderSide.SELL
        quantity = self._quantity(instrument_id, abs(change))
        self.submit_order(self.order_factory.market(instrument_id, side, quantity))

    def _quantity(self, instrument_id: InstrumentId, amount: Decimal) -> Quantity:
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            raise LookupError(f"instrument {instrument_id} is not in the cache")
        return instrument.make_qty(amount)


def _bar(params: CrossParams) -> BarSpecification:
    return BarSpecification.from_str(params.bar)
