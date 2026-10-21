from collections.abc import Mapping
from decimal import Decimal
from typing import Any, override

from nautilus_trader.model import Price, Quantity

from sbt2.core.assets.delivery.convention import DeliverySettlement
from sbt2.core.assets.delivery.fee_model import DeliveryFeeModel

_RATE = Decimal("0.00025")


class FutureSettlement(DeliverySettlement):
    """A dated future expires at the delivery price; the ``rate`` of its
    ``delivery_fee`` setting is the part of the notional the fee takes."""

    @override
    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        rate = _rate(venue.get("delivery_fee", {}))
        return {**venue, "delivery_fee": {"rate": f"{rate:f}"}}

    @override
    def fee_model(self, base: Any, venue: Mapping[str, Any], tag: str) -> Any:
        return FutureDeliveryFeeModel(base, _rate(venue["delivery_fee"]), tag)


class FutureDeliveryFeeModel(DeliveryFeeModel):
    """Charges ``rate`` of the notional, in the coin, on the settlement of an
    inverse future."""

    def __init__(self, inner: Any, rate: Decimal, tag: str) -> None:
        super().__init__(inner, tag)
        self._rate = rate

    @override
    def _delivery_fee(
        self, quantity: Quantity, price: Price, instrument: Any
    ) -> Decimal:
        usd = Decimal(str(quantity)) * Decimal(str(instrument.multiplier))
        return self._rate * usd / Decimal(str(price))


def _rate(table: Mapping[str, Any]) -> Decimal:
    unknown = sorted(set(table) - {"rate"})
    if unknown:
        raise ValueError(f"the delivery_fee setting has no {', '.join(unknown)}")
    try:
        rate = Decimal(str(table.get("rate", _RATE)))
    except ArithmeticError as error:
        raise ValueError(f"the delivery_fee rate is invalid: {error}") from error
    if not rate.is_finite() or rate < 0:
        raise ValueError(f"the delivery_fee rate {rate} is not a rate")
    return rate
