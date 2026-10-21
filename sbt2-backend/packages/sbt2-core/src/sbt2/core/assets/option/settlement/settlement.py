from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Self

from nautilus_trader.model import CryptoOption, OptionKind


def settlement_price(contract: CryptoOption, delivery: Decimal) -> Decimal:
    """What one contract is worth at expiry, in the underlying coin: the intrinsic
    value in USD over the delivery price ``delivery``."""
    strike = Decimal(str(contract.strike_price))
    if contract.option_kind == OptionKind.CALL:
        intrinsic = delivery - strike
    else:
        intrinsic = strike - delivery
    return max(Decimal(0), intrinsic) / delivery


@dataclass(frozen=True)
class DeliveryFee:
    """The fee of a settlement: ``rate`` of the underlying, at most ``cap_rate``
    of the settlement value."""

    rate: Decimal = Decimal("0.00015")
    cap_rate: Decimal = Decimal("0.125")

    def __post_init__(self) -> None:
        if self.rate < 0 or self.cap_rate < 0:
            raise ValueError("the rates are not negative")

    @classmethod
    def from_table(cls, table: Mapping[str, Any]) -> Self:
        """The fee the ``delivery_fee`` table of a spec's ``[execution]`` sets, with a default for
        each rate it leaves out; ``ValueError`` when the table is invalid."""
        try:
            return cls(**{name: Decimal(str(rate)) for name, rate in table.items()})
        except (TypeError, ArithmeticError, ValueError) as error:
            raise ValueError(f"the delivery_fee setting is invalid: {error}") from error

    def amount(self, underlying: Decimal, value: Decimal) -> Decimal:
        return min(self.rate * underlying, self.cap_rate * value)
