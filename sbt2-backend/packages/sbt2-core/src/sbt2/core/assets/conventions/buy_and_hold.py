from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from nautilus_trader.model import MarkPriceUpdate

from sbt2.core.assets.conventions.carry import Carry


class NoTakerRateError(LookupError):
    pass


@dataclass(frozen=True)
class BuyAndHoldConvention:
    """How a benchmark holds an instrument: bought once, then valued at ``price``.

    ``carry`` is what the holding accrues on top of the price.
    """

    price: type
    carry: Carry

    def entry_fee(self, venue: Mapping[str, Any]) -> Decimal:
        """The taker rate of the venue's fee model, paid once on entry.

        ``venue`` holds the run's venue arguments, the fee model as its
        ``{kind, config}`` table.
        """
        fee_model = venue.get("fee_model") or {}
        rate = fee_model.get("config", {}).get("taker_rate")
        if rate is None:
            name = fee_model.get("kind", "the venue's missing fee model")
            raise NoTakerRateError(f"{name} has no taker rate for a benchmark entry")
        return Decimal(str(rate))


class NoBuyAndHoldError(LookupError):
    pass


@dataclass(frozen=True)
class NoBuyAndHold(BuyAndHoldConvention):
    """The convention of an instrument that cannot be held as a benchmark."""

    price: type = MarkPriceUpdate
    carry: Carry = field(default_factory=lambda: Carry(data_types=()))
    reason: str = ""

    def entry_fee(self, venue: Mapping[str, Any]) -> Decimal:
        del venue
        raise NoBuyAndHoldError(f"no buy-and-hold benchmark: {self.reason}")
