from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

from nautilus_trader.indicators import SimpleMovingAverage
from nautilus_trader.model import (
    Bar,
    BarSpecification,
    InstrumentId,
    Money,
    OrderSide,
    Price,
    Quantity,
)
from nautilus_trader.risk import FixedRiskSizer

from sbt2.strategy import Strategy


@dataclass(frozen=True)
class BracketParams:
    """``stop`` is the stop-loss distance as a fraction of the entry price,
    ``reward`` the take-profit distance in stop distances and ``risk`` the
    fraction of equity a stop-loss fill loses."""

    period: int = 12
    bar: str = "1-HOUR-LAST"
    risk: Decimal = Decimal("0.01")
    stop: Decimal = Decimal("0.005")
    reward: Decimal = Decimal(2)


@dataclass(frozen=True)
class Entry:
    side: OrderSide
    price: Price
    equity: Money


@dataclass(frozen=True)
class Bracket:
    quantity: Quantity
    stop_loss: Price
    take_profit: Price


def plan_bracket(instrument: Any, entry: Entry, params: BracketParams) -> Bracket:
    """The exits ``params`` puts around ``entry``, and the quantity that loses
    ``risk`` of the equity at the stop-loss."""
    price = entry.price.as_decimal()
    distance = price * params.stop * (1 if entry.side == OrderSide.BUY else -1)
    stop_loss = instrument.make_price(float(price - distance))
    take_profit = instrument.make_price(float(price + params.reward * distance))
    quantity = FixedRiskSizer(instrument).calculate(
        entry.price,
        stop_loss,
        entry.equity,
        params.risk,
        unit_batch_size=instrument.size_increment.as_decimal(),
    )
    return Bracket(quantity, stop_loss, take_profit)


class BracketRisk(Strategy[BracketParams]):
    """On each instrument, whenever it has no position and no order, enters a
    bracket: long when a bar closes above its moving average, short below.

    The entry is a market order; its stop-loss and take-profit are placed by
    ``plan_bracket``.
    """

    Params = BracketParams

    @classmethod
    def warmup(cls, params: BracketParams) -> timedelta:
        return params.period * _bar(params).timedelta

    @classmethod
    def inputs(cls, params: BracketParams) -> Sequence[BarSpecification]:
        return (_bar(params),)

    def on_start(self) -> None:
        super().on_start()
        self.averages: dict[str, SimpleMovingAverage] = {}
        for bar_type in self.bar_types():
            average = SimpleMovingAverage(self.params.period)
            self.register_indicator_for_bars(bar_type, average)
            self.averages[str(bar_type)] = average

    def on_bar(self, bar: Bar) -> None:
        instrument_id = bar.bar_type.instrument_id
        side = _side(bar, self.averages[str(bar.bar_type)])
        if side is None or not self._idle(instrument_id):
            return
        self._enter(instrument_id, Entry(side, bar.close, self._equity(instrument_id)))

    def _idle(self, instrument_id: InstrumentId) -> bool:
        return self.portfolio.net_position(instrument_id) == 0 and not (
            self.cache.orders_open(instrument_id=instrument_id)
        )

    def _enter(self, instrument_id: InstrumentId, entry: Entry) -> None:
        bracket = plan_bracket(self._instrument(instrument_id), entry, self.params)
        if bracket.quantity.as_decimal() == 0:
            return
        orders = self.order_factory.bracket(
            instrument_id,
            entry.side,
            bracket.quantity,
            tp_price=bracket.take_profit,
            sl_trigger_price=bracket.stop_loss,
        )
        self.submit_order_list(orders)

    def _equity(self, instrument_id: InstrumentId) -> Money:
        instrument = self._instrument(instrument_id)
        account = self.portfolio.account(instrument_id.venue)
        balance = (
            None
            if account is None
            else account.balance_total(instrument.settlement_currency)
        )
        if balance is None:
            raise LookupError(f"no balance to size {instrument_id}")
        return balance

    def _instrument(self, instrument_id: InstrumentId) -> Any:
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            raise LookupError(f"instrument {instrument_id} is not in the cache")
        return instrument


def _side(bar: Bar, average: SimpleMovingAverage) -> OrderSide | None:
    close = bar.close.as_double()
    if not average.initialized or close == average.value:
        return None
    return OrderSide.BUY if close > average.value else OrderSide.SELL


def _bar(params: BracketParams) -> BarSpecification:
    return BarSpecification.from_str(params.bar)
