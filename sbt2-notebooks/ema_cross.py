from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from nautilus_trader.indicators import ExponentialMovingAverage
from nautilus_trader.model import (
    Bar,
    BarSpecification,
    InstrumentId,
    OrderSide,
    Quantity,
)

from sbt2.core.strategy import Strategy


@dataclass(frozen=True)
class EmaCrossParams:
    fast: int = 12
    slow: int = 48
    bar: str = "1-HOUR-LAST"
    quantity: Decimal = Decimal("0.100")


class EmaCross(Strategy[EmaCrossParams]):
    """Long ``quantity`` while the fast EMA is above the slow one, flat below."""

    Params = EmaCrossParams

    @classmethod
    def warmup(cls, params: EmaCrossParams) -> timedelta:
        return params.slow * BarSpecification.from_str(params.bar).timedelta

    @classmethod
    def inputs(cls, params: EmaCrossParams) -> Sequence[BarSpecification]:
        return (BarSpecification.from_str(params.bar),)

    def on_start(self) -> None:
        super().on_start()
        self.emas: dict[str, tuple[ExponentialMovingAverage, ...]] = {}
        for bar_type in self.bar_types():
            fast = ExponentialMovingAverage(self.params.fast)
            slow = ExponentialMovingAverage(self.params.slow)
            self.register_indicator_for_bars(bar_type, fast)
            self.register_indicator_for_bars(bar_type, slow)
            self.emas[str(bar_type)] = (fast, slow)

    def on_bar(self, bar: Bar) -> None:
        fast, slow = self.emas[str(bar.bar_type)]
        if not slow.initialized:
            return
        target = self.params.quantity if fast.value > slow.value else Decimal(0)
        self._trade_to(bar.bar_type.instrument_id, target)

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
