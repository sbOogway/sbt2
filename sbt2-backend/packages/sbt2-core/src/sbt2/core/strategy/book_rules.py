from decimal import Decimal
from typing import Any

from sbt2.core.strategy.chain import NoMarketError
from sbt2.core.strategy.combo import Combo
from sbt2.core.strategy.short_premium import BookState, ComboProposal, ShortPremiumRules


class BookRules:
    """The short premium rules applied to the book of a strategy: what it holds,
    read from ``strategy``, against a combo it is about to open."""

    def __init__(self, rules: ShortPremiumRules, strategy: Any) -> None:
        self._rules = rules
        self._strategy = strategy

    def refusal(self, combo: Combo) -> str | None:
        """Why the rules refuse ``combo``, or none when it passes."""
        try:
            proposal = ComboProposal(
                self._strategy.margin_of_combo(combo), combo.defined_risk
            )
            return self._rules.refusal(self._book(combo), proposal)
        except LookupError as error:
            return f"the BPR of the combo cannot be priced: {error}"

    def _book(self, combo: Combo) -> BookState:
        return BookState(
            self._equity(combo),
            self._iv_rank(),
            sum(self._strategy.margin_of_positions().values(), Decimal(0)),
            sum(
                (
                    self._strategy.margin_of_combo(each)
                    for each in self._strategy.combos
                    if each.defined_risk
                ),
                Decimal(0),
            ),
        )

    def _equity(self, combo: Combo) -> Decimal:
        """The account's total balance in the settlement currency of the combo."""
        contract = combo.legs[0].contract
        account = self._strategy.portfolio.account(contract.id.venue)
        return account.balance_total(contract.settlement_currency).as_decimal()

    def _iv_rank(self) -> float | None:
        try:
            return self._strategy.chain.iv_rank()
        except NoMarketError:
            return None
