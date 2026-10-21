from decimal import Decimal
from typing import Any, override

from nautilus_trader.model import Price, Quantity

from sbt2.core.assets.delivery.fee_model import DeliveryFeeModel
from sbt2.core.assets.option.settlement.settlement import DeliveryFee


class OptionDeliveryFeeModel(DeliveryFeeModel):
    """Charges ``fee`` on the settlement of an option."""

    def __init__(self, inner: Any, fee: DeliveryFee, tag: str) -> None:
        super().__init__(inner, tag)
        self._fee = fee

    @override
    def _delivery_fee(
        self, quantity: Quantity, price: Price, instrument: Any
    ) -> Decimal:
        underlying = Decimal(str(quantity)) * Decimal(str(instrument.multiplier))
        value = underlying * Decimal(str(price))
        return self._fee.amount(underlying, value)
