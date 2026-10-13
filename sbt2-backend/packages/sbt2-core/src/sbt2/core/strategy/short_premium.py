from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class ShortPremiumRules:
    """The portfolio rules of a short premium book, as fractions of equity.

    ``allocation`` is the share of equity the buying power reduction (BPR) of all
    open positions may use at an IV rank of 0 and of 1, linear between.
    ``undefined_cap`` and ``defined_cap`` cap the BPR of one combo of undefined
    and of defined risk. ``defined_share`` caps the BPR of the defined-risk
    combos as a share of the allocation.
    """

    allocation: tuple[Decimal, Decimal] = (Decimal("0.25"), Decimal("0.50"))
    undefined_cap: Decimal = Decimal("0.07")
    defined_cap: Decimal = Decimal("0.05")
    defined_share: Decimal = Decimal("0.25")

    def as_primitives(self) -> dict[str, Any]:
        """The rules as the strings and lists of a spec table."""
        return {
            "allocation": [str(each) for each in self.allocation],
            "undefined_cap": str(self.undefined_cap),
            "defined_cap": str(self.defined_cap),
            "defined_share": str(self.defined_share),
        }

    @classmethod
    def from_primitives(cls, table: dict[str, Any]) -> ShortPremiumRules:
        low, high = table["allocation"]
        return cls(
            (Decimal(low), Decimal(high)),
            Decimal(table["undefined_cap"]),
            Decimal(table["defined_cap"]),
            Decimal(table["defined_share"]),
        )
