from collections.abc import Callable, Iterable, Mapping
from decimal import Decimal
from typing import Any

from sbt2.core.strategy.chain import NoMarketError


class Conversion:
    """Converts amounts between the coins of a run at the latest USD index price
    of each, which ``prices`` gives by the code of the coin."""

    def __init__(self, prices: Callable[[], Mapping[str, float]]) -> None:
        self._prices = prices

    def convert(self, amount: Decimal, route: tuple[str, str]) -> Decimal:
        """``amount`` of the coin ``route[0]`` in the coin ``route[1]``;
        ``NoMarketError`` when a price is not heard yet."""
        source, target = route
        if source == target:
            return amount
        prices = self._prices()
        try:
            ratio = prices[source] / prices[target]
        except KeyError as error:
            raise NoMarketError(
                f"no index price of {error} to convert {source}"
            ) from error
        return amount * Decimal(str(ratio))

    def total(self, amounts: Iterable[tuple[Decimal, str]], coin: str) -> Decimal:
        """The ``amounts``, each with the coin it is in, added in ``coin``."""
        return sum(
            (self.convert(amount, (own, coin)) for amount, own in amounts),
            Decimal(0),
        )

    def balances(self, account: Any, coin: str) -> Decimal:
        """The total balances of all coins of ``account``, in ``coin``."""
        held = account.balances_total().values()
        return self.total(
            ((each.as_decimal(), each.currency.code) for each in held), coin
        )
