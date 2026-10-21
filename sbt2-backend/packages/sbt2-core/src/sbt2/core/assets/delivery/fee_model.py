from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, override

from nautilus_trader.execution import FeeModel
from nautilus_trader.model import Money, Price, Quantity


class DeliveryFeeModel(FeeModel, ABC):
    """Charges the delivery fee on the orders tagged ``tag``, which close the
    positions of an expired contract, and ``inner`` on all others; no fee when
    ``inner`` is ``None``."""

    def __init__(self, inner: Any, tag: str) -> None:
        super().__init__()
        self._inner = inner
        self._tag = tag

    @override
    def get_commission(
        self, order: Any, fill_quantity: Quantity, fill_px: Price, instrument: Any
    ) -> Money:
        if self._tag in (order.tags or ()):
            amount = self._delivery_fee(fill_quantity, fill_px, instrument)
            return Money(float(amount), instrument.settlement_currency)
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

    @abstractmethod
    def _delivery_fee(
        self, quantity: Quantity, price: Price, instrument: Any
    ) -> Decimal:
        """The fee of settling ``quantity`` of ``instrument`` at ``price``, in its
        settlement currency."""
        ...
