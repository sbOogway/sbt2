from dataclasses import dataclass
from decimal import Decimal

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

    rate: Decimal
    cap_rate: Decimal

    def amount(self, underlying: Decimal, value: Decimal) -> Decimal:
        return min(self.rate * underlying, self.cap_rate * value)
