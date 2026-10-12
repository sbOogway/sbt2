from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum, auto
from typing import Any

from nautilus_trader.model import ClientOrderId, InstrumentId, OrderFilled

from sbt2.core.strategy.combo import Combo

COMBO_TAG_PREFIX = "COMBO:"


def combo_tag(combo_id: str) -> str:
    return f"{COMBO_TAG_PREFIX}{combo_id}"


class Change(Enum):
    """What a fill did to a combo."""

    OPENED = auto()
    CLOSED = auto()
    SETTLED = auto()


class _Role(Enum):
    OPEN = auto()
    CLOSE = auto()
    SETTLE = auto()


@dataclass
class _Tracked:
    combo: Combo
    cost: dict[InstrumentId, Decimal] = field(default_factory=dict)
    filled: dict[InstrumentId, Decimal] = field(default_factory=dict)
    remaining: dict[InstrumentId, Decimal] = field(default_factory=dict)
    opened: bool = False
    closing: bool = False
    settled: bool = False

    def fill_leg(self, fill: OrderFilled) -> bool:
        """Count an opening fill; whether the last leg is now filled."""
        key, quantity = fill.instrument_id, Decimal(str(fill.last_qty))
        price = Decimal(str(fill.last_px))
        self.filled[key] = self.filled.get(key, Decimal(0)) + quantity
        self.cost[key] = self.cost.get(key, Decimal(0)) + quantity * price
        return all(
            self.filled.get(leg.contract.id, Decimal(0)) >= leg.quantity
            for leg in self.combo.legs
        )

    def open(self) -> None:
        entries = {each: self.cost[each] / self.filled[each] for each in self.filled}
        self.combo = self.combo.priced(entries)
        self.remaining = dict(self.filled)
        self.opened = True

    def close_leg(self, fill: OrderFilled) -> bool:
        """Count a closing fill; whether no leg is left."""
        if fill.instrument_id not in self.remaining:
            return not self.remaining
        left = self.remaining[fill.instrument_id] - Decimal(str(fill.last_qty))
        if left > 0:
            self.remaining[fill.instrument_id] = left
        else:
            del self.remaining[fill.instrument_id]
        return not self.remaining


class ComboBook:
    """The combos of a strategy from the orders of their legs: it counts the fills
    and says when a combo opened, closed or settled."""

    def __init__(self) -> None:
        self._tracked: dict[str, _Tracked] = {}
        self._orders: dict[ClientOrderId, list[tuple[str, _Role]]] = {}
        self._count = 0

    def next_id(self) -> str:
        self._count += 1
        return f"C{self._count}"

    def opening(self, combo: Combo, orders: Sequence[Any]) -> None:
        self._tracked[combo.id] = _Tracked(combo)
        self._expect(combo.id, orders, _Role.OPEN)

    def closing(self, combo_id: str, orders: Sequence[Any]) -> None:
        self._tracked[combo_id].closing = True
        self._expect(combo_id, orders, _Role.CLOSE)

    def settling(self, instrument_id: InstrumentId, order: Any) -> None:
        for combo_id in self.holding(instrument_id):
            self._orders.setdefault(order.client_order_id, []).append(
                (combo_id, _Role.SETTLE)
            )

    def forget(self, orders: Sequence[Any]) -> None:
        """The orders were not sent: a combo they opened never was, and one they
        closed is still open."""
        for order in orders:
            for combo_id, role in self._orders.pop(order.client_order_id, []):
                self._unsent(combo_id, role)

    def opened(self) -> tuple[Combo, ...]:
        return tuple(each.combo for each in self._tracked.values() if each.opened)

    def is_closing(self, combo_id: str) -> bool:
        return self._tracked[combo_id].closing

    def remaining(self, combo_id: str) -> dict[InstrumentId, Decimal]:
        """The quantity of each leg of an opened combo that is still held."""
        return dict(self._tracked[combo_id].remaining)

    def holding(self, instrument_id: InstrumentId) -> list[str]:
        return [
            combo_id
            for combo_id, each in self._tracked.items()
            if instrument_id in each.remaining
        ]

    def hear(self, fill: OrderFilled) -> list[tuple[Change, Combo]]:
        changes = []
        for combo_id, role in self._orders.get(fill.client_order_id, []):
            change = self._filled(self._tracked[combo_id], fill, role)
            if change is not None:
                changes.append((change, self._tracked[combo_id].combo))
                self._finish(combo_id, change)
        return changes

    def _expect(self, combo_id: str, orders: Sequence[Any], role: _Role) -> None:
        for order in orders:
            self._orders.setdefault(order.client_order_id, []).append((combo_id, role))

    def _unsent(self, combo_id: str, role: _Role) -> None:
        if role == _Role.OPEN:
            self._tracked.pop(combo_id, None)
        elif combo_id in self._tracked:
            self._tracked[combo_id].closing = False

    def _filled(
        self, tracked: _Tracked, fill: OrderFilled, role: _Role
    ) -> Change | None:
        if role == _Role.OPEN:
            if tracked.fill_leg(fill) and not tracked.opened:
                tracked.open()
                return Change.OPENED
            return None
        tracked.settled |= role == _Role.SETTLE
        if not tracked.close_leg(fill):
            return None
        return Change.SETTLED if tracked.settled else Change.CLOSED

    def _finish(self, combo_id: str, change: Change) -> None:
        if change == Change.OPENED:
            return
        del self._tracked[combo_id]
        for orders in self._orders.values():
            orders[:] = [each for each in orders if each[0] != combo_id]
