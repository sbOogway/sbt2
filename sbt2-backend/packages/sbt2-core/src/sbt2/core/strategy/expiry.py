from typing import Any

from nautilus_trader.model import InstrumentClass, OrderSide, PositionSide

SETTLEMENT_TAG = "SETTLEMENT"


def settlement_time(instrument: Any) -> int | None:
    """When to settle the positions in ``instrument``, in nanoseconds: one before
    an option expires, as nautilus rejects the orders of an expired contract.
    None for an instrument that does not expire."""
    if instrument is None or instrument.instrument_class != InstrumentClass.OPTION:
        return None
    return int(instrument.expiration_ns) - 1


def closing_side(position: Any) -> OrderSide:
    return OrderSide.SELL if position.side == PositionSide.LONG else OrderSide.BUY
