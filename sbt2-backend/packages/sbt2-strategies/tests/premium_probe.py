from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import ClassVar, override

from sbt2.core.strategy import Combo
from sbt2.strategies.premium_portfolio import PremiumPortfolio


@dataclass(frozen=True)
class Submission:
    """A combo as the portfolio sent it: its BPR and the equity it was sized on."""

    combo: Combo
    bpr: Decimal
    equity: Decimal


class ProbePortfolio(PremiumPortfolio):
    """A portfolio that notes what it sends, what the rules refuse and the combos
    held when each one opens."""

    submitted: ClassVar[list[Submission]] = []
    declined: ClassVar[list[tuple[datetime, Combo]]] = []
    opened: ClassVar[list[tuple[Combo, tuple[Combo, ...]]]] = []

    @classmethod
    def clear(cls) -> None:
        for each in (cls.submitted, cls.declined, cls.opened):
            each.clear()

    @override
    def open_combo(self, combo: Combo) -> Combo:
        contract = combo.legs[0].contract
        equity = self.equity(contract.settlement_currency.code)
        self.submitted.append(Submission(combo, self.margin_of_combo(combo), equity))
        return super().open_combo(combo)

    @override
    def on_combo_refused(self, combo: Combo, reason: str) -> None:
        self.declined.append((self.clock.utc_now(), combo))

    @override
    def on_combo_opened(self, combo: Combo) -> None:
        self.opened.append((combo, self.combos))


class OversizedPortfolio(ProbePortfolio):
    """A portfolio that sends combos ten times the size it works out, which the
    rules refuse."""

    @override
    def open_combo(self, combo: Combo) -> Combo:
        legs = tuple(replace(leg, quantity=leg.quantity * 10) for leg in combo.legs)
        return super().open_combo(replace(combo, legs=legs))
