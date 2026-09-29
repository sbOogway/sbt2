from decimal import Decimal


class DrawdownGuard:
    """Follows peak equity and tells when equity falls more than ``limit``
    of it below the peak."""

    def __init__(self, limit: Decimal) -> None:
        self._limit = limit
        self._peak: Decimal | None = None

    def breached(self, equity: Decimal) -> bool:
        self._peak = equity if self._peak is None else max(self._peak, equity)
        return equity < self._peak * (1 - self._limit)
