from decimal import Decimal
from typing import Any, override

from nautilus_trader.execution import FeeModel
from nautilus_trader.model import Money, Price, Quantity

from sbt2.core.assets.option_settlement import DeliveryFee


class DeliveryFeeModel(FeeModel):
    """Charges the delivery fee on the orders tagged ``tag``, which close the
    positions of an expired contract, and ``inner`` on all others; no fee when
    ``inner`` is ``None``."""

    def __init__(self, inner: Any, fee: DeliveryFee, tag: str) -> None:
        super().__init__()
        self._inner = inner
        self._fee = fee
        self._tag = tag

    @override
    def get_commission(
        self, order: Any, fill_quantity: Quantity, fill_px: Price, instrument: Any
    ) -> Money:
        if self._tag in (order.tags or ()):
            return self._delivery(fill_quantity, fill_px, instrument)
        if self._inner is None:
            return Money.zero(instrument.settlement_currency)
        return self._inner.get_commission(order, fill_quantity, fill_px, instrument)

    @override
    def get_commission_with_context(
        self,
        order: Any,
        fill_quantity: Quantity,
        fill_px: Price,
        instrument: Any,
        underlying_px: Price | None = None,
    ) -> Money:
        if self._inner is None or self._tag in (order.tags or ()):
            return self.get_commission(order, fill_quantity, fill_px, instrument)
        return self._inner.get_commission_with_context(
            order, fill_quantity, fill_px, instrument, underlying_px
        )

    def _delivery(self, quantity: Quantity, price: Price, instrument: Any) -> Money:
        underlying = Decimal(str(quantity)) * Decimal(str(instrument.multiplier))
        value = underlying * Decimal(str(price))
        amount = self._fee.amount(underlying, value)
        return Money(float(amount), instrument.settlement_currency)
