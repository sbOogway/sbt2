from collections.abc import Sequence
from decimal import Decimal
from typing import Any, Protocol

from nautilus_trader.model import InstrumentId, OrderSide, PositionSide


class MarginModel(Protocol):
    """The margin of a position, in its settlement currency; ``quantity`` is
    signed and ``ts`` is in nanoseconds."""

    def initial(self, instrument: Any, quantity: Decimal, ts: int) -> Decimal: ...

    def value(self, instrument: Any, quantity: Decimal, ts: int) -> Decimal: ...


class MarginDesk:
    """What a strategy asks about margin: ``model`` priced for the strategy's
    open positions and the orders it is about to send."""

    def __init__(self, model: MarginModel, trader: Any) -> None:
        self._model = model
        self._trader = trader

    def of_order(self, order: Any) -> Decimal:
        """What the order adds to the margin of its position; none when it only
        reduces the position."""
        return max(Decimal(0), self._added([order]))

    def _added(self, orders: Sequence[Any]) -> Decimal:
        ts = self._trader.clock.timestamp_ns()
        held = self._held()
        total = Decimal(0)
        for instrument_id, change in _changes(orders).items():
            instrument = self._trader.cache.instrument(instrument_id)
            before = held.get(instrument_id, Decimal(0))
            total += self._model.initial(
                instrument, before + change, ts
            ) - self._model.initial(instrument, before, ts)
        return total

    def _held(self) -> dict[InstrumentId, Decimal]:
        """The signed quantity of each open position."""
        return {
            position.instrument_id: _signed(position)
            for position in self._trader.cache.positions_open()
        }


def _changes(orders: Sequence[Any]) -> dict[InstrumentId, Decimal]:
    changes: dict[InstrumentId, Decimal] = {}
    for order in orders:
        sign = 1 if order.side == OrderSide.BUY else -1
        quantity = sign * Decimal(str(order.quantity))
        changes[order.instrument_id] = changes.get(order.instrument_id, 0) + quantity
    return changes


def _signed(position: Any) -> Decimal:
    quantity = Decimal(str(position.quantity))
    return quantity if position.side == PositionSide.LONG else -quantity
