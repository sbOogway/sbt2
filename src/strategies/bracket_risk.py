from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from nautilus_trader.model import Money, OrderSide, Price, Quantity
from nautilus_trader.risk import FixedRiskSizer


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
