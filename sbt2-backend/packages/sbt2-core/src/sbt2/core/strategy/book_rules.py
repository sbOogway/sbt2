from collections.abc import Iterable
from decimal import Decimal
from typing import Any

from nautilus_trader.model import CryptoOption

from sbt2.core.strategy.chain import NoMarketError
from sbt2.core.strategy.combo import Combo
from sbt2.core.strategy.conversion import Conversion
from sbt2.core.strategy.short_premium import BookState, ComboProposal, ShortPremiumRules


def account_equity(trader: Any, contract: CryptoOption) -> Decimal:
    """The account's total balance in the settlement currency of ``contract``."""
    account = trader.portfolio.account(contract.id.venue)
    return account.balance_total(contract.settlement_currency).as_decimal()


class BookRules:
    """The short premium rules applied to the book of a strategy: what it holds,
    read from ``strategy``, against a combo it is about to open. A book of several
    coins weighs in the settlement coin of the combo, which ``conversion``
    gives."""

    def __init__(
        self, rules: ShortPremiumRules, strategy: Any, conversion: Conversion
    ) -> None:
        self._rules = rules
        self._strategy = strategy
        self._conversion = conversion

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
        contract = combo.legs[0].contract
        coin = _coin(contract)
        account = self._strategy.portfolio.account(contract.id.venue)
        balances = account.balances_total().values()
        margins = self._strategy.margin_of_positions()
        return BookState(
            self._total(
                coin, [(each.as_decimal(), each.currency.code) for each in balances]
            ),
            self._iv_rank(combo),
            self._total(
                coin,
                [(margin, self._coin_of(each)) for each, margin in margins.items()],
            ),
            self._total(coin, self._defined()),
        )

    def _total(self, coin: str, amounts: Iterable[tuple[Decimal, str]]) -> Decimal:
        """The ``amounts``, each with the coin it is in, added in ``coin``."""
        return sum(
            (self._conversion.convert(amount, (own, coin)) for amount, own in amounts),
            Decimal(0),
        )

    def _coin_of(self, instrument_id: Any) -> str:
        return self._strategy.cache.instrument(instrument_id).settlement_currency.code

    def _defined(self) -> list[tuple[Decimal, str]]:
        """The BPR of each open defined-risk combo, with its coin."""
        return [
            (self._strategy.margin_of_combo(each), _coin(each.legs[0].contract))
            for each in self._strategy.combos
            if each.defined_risk
        ]

    def _iv_rank(self, combo: Combo) -> float | None:
        try:
            chain = self._strategy.chains[combo.legs[0].contract.underlying.code]
            return chain.iv_rank()
        except NoMarketError:
            return None


def _coin(contract: CryptoOption) -> str:
    return contract.settlement_currency.code
