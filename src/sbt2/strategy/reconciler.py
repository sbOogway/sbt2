from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from nautilus_trader.model import InstrumentId

from sbt2.strategy.api import TargetPosition


@dataclass(frozen=True)
class WorkingOrder:
    """An order still working at the venue; ``quantity`` is its signed leaves quantity."""

    order_id: str
    instrument_id: InstrumentId
    quantity: Decimal


@dataclass(frozen=True)
class PlaceMarket:
    instrument_id: InstrumentId
    quantity: Decimal


@dataclass(frozen=True)
class Cancel:
    order_id: str


type OrderAction = PlaceMarket | Cancel


def reconcile(
    targets: Sequence[TargetPosition],
    positions: Mapping[InstrumentId, Decimal],
    working: Sequence[WorkingOrder],
) -> list[OrderAction]:
    """Order actions that move each targeted instrument from its real position to its target.

    Working orders are kept while they all move towards the target without
    overshooting it, and the rest is placed. Otherwise they are all canceled and
    the whole difference is placed. Instruments without a target are left alone.
    """
    latest = {target.instrument_id: target.quantity for target in targets}
    return [
        action
        for instrument_id, target in latest.items()
        for action in _reconcile_instrument(
            instrument_id,
            target - positions.get(instrument_id, Decimal(0)),
            [order for order in working if order.instrument_id == instrument_id],
        )
    ]


def _reconcile_instrument(
    instrument_id: InstrumentId, needed: Decimal, working: list[WorkingOrder]
) -> list[OrderAction]:
    if _moves_towards(working, needed):
        return _place(instrument_id, needed - _total(working))
    cancels: list[OrderAction] = [Cancel(order.order_id) for order in working]
    return cancels + _place(instrument_id, needed)


def _moves_towards(working: list[WorkingOrder], needed: Decimal) -> bool:
    same_side = all(order.quantity * needed > 0 for order in working)
    return same_side and abs(_total(working)) <= abs(needed)


def _total(working: list[WorkingOrder]) -> Decimal:
    return sum((order.quantity for order in working), Decimal(0))


def _place(instrument_id: InstrumentId, quantity: Decimal) -> list[OrderAction]:
    return [PlaceMarket(instrument_id, quantity)] if quantity else []
