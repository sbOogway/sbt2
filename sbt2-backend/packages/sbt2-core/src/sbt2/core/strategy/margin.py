from collections.abc import Mapping, Sequence
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

    def of_positions(self) -> dict[InstrumentId, Decimal]:
        """The initial margin of each open position."""
        ts = self._trader.clock.timestamp_ns()
        return {
            instrument_id: self._model.initial(
                self._trader.cache.instrument(instrument_id), quantity, ts
            )
            for instrument_id, quantity in self._held().items()
        }

    def of_quantities(self, quantities: Mapping[InstrumentId, Decimal]) -> Decimal:
        """The initial margin of the signed quantities, each held alone."""
        ts = self._trader.clock.timestamp_ns()
        return sum(
            (
                self._model.initial(self._trader.cache.instrument(each), quantity, ts)
                for each, quantity in quantities.items()
            ),
            Decimal(0),
        )

    def refusal(self, orders: Sequence[Any]) -> str | None:
        """Why the orders cannot be sent, or none when the free equity covers
        the margin they add."""
        try:
            added = self._added(orders)
            free = self._free_equity(orders[0].instrument_id)
        except LookupError as error:
            return f"the margin of the orders cannot be priced: {error}"
        if added <= 0 or added <= free:
            return None
        return f"the orders need an initial margin of {added}, above the free equity {free}"

    def _free_equity(self, instrument_id: InstrumentId) -> Decimal:
        """The equity less the initial margin of the open positions, in the
        currency of ``instrument_id``."""
        ts = self._trader.clock.timestamp_ns()
        currency = self._trader.cache.instrument(instrument_id).settlement_currency
        account = self._trader.portfolio.account(instrument_id.venue)
        free = account.balance_total(currency).as_decimal()
        for held_id, quantity in self._held().items():
            held = self._trader.cache.instrument(held_id)
            free += self._model.value(held, quantity, ts)
            free -= self._model.initial(held, quantity, ts)
        return free

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
