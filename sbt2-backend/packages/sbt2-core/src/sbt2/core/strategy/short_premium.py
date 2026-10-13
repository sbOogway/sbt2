from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class BookState:
    """What the rules weigh a combo against: the ``equity``, the IV rank (none
    when unknown), the BPR of all open positions and the BPR of the open
    defined-risk combos, all in the settlement currency."""

    equity: Decimal
    iv_rank: float | None
    bpr: Decimal
    defined_bpr: Decimal


@dataclass(frozen=True)
class ComboProposal:
    """A combo about to open: its BPR and whether its risk is defined."""

    bpr: Decimal
    defined_risk: bool


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

    def allocation_at(self, iv_rank: float | None) -> Decimal:
        """The share of equity the book may use at ``iv_rank``; the low end
        without a rank."""
        low, high = self.allocation
        if iv_rank is None:
            return low
        position = Decimal(str(min(max(iv_rank, 0.0), 1.0)))
        return low + (high - low) * position

    def refusal(self, book: BookState, combo: ComboProposal) -> str | None:
        """Why the rules refuse ``combo`` on ``book``, naming the rule and the
        numbers; none when it passes."""
        return (
            self._over_cap(book, combo)
            or self._over_allocation(book, combo)
            or self._over_share(book, combo)
        )

    def _over_cap(self, book: BookState, combo: ComboProposal) -> str | None:
        name = "defined_cap" if combo.defined_risk else "undefined_cap"
        cap = self.defined_cap if combo.defined_risk else self.undefined_cap
        limit = book.equity * cap
        if combo.bpr <= limit:
            return None
        return (
            f"{name}: the combo's BPR {combo.bpr} is above {limit}, "
            f"{cap} of the equity {book.equity}"
        )

    def _over_allocation(self, book: BookState, combo: ComboProposal) -> str | None:
        share = self.allocation_at(book.iv_rank)
        limit = book.equity * share
        total = book.bpr + combo.bpr
        if total <= limit:
            return None
        return (
            f"allocation: the BPR of the book would be {total}, above {limit}, "
            f"{share} of the equity {book.equity}"
        )

    def _over_share(self, book: BookState, combo: ComboProposal) -> str | None:
        if not combo.defined_risk:
            return None
        share = self.defined_share * self.allocation_at(book.iv_rank)
        limit = book.equity * share
        total = book.defined_bpr + combo.bpr
        if total <= limit:
            return None
        return (
            f"defined_share: the BPR of defined-risk combos would be {total}, "
            f"above {limit}, {share} of the equity {book.equity}"
        )

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
