from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Self

from nautilus_trader.model import CryptoOption, OptionKind


@dataclass(frozen=True)
class ContractHolding:
    """``quantity`` contracts of ``contract``, negative when short."""

    contract: CryptoOption
    quantity: Decimal


@dataclass(frozen=True)
class OptionQuote:
    """What the margin of a contract is taken at: its ``mark`` in the underlying
    coin and the ``index`` price in USD."""

    mark: Decimal
    index: Decimal


@dataclass(frozen=True)
class MarginRates:
    """Deribit's standard margin of an option, in the underlying coin per contract.

    A long option needs its mark. A short one needs ``base_rate`` less its OTM
    amount over the index, at least ``floor_rate``, plus its mark; a short put at
    least its maintenance margin, which is ``maintenance_rate`` plus its mark.
    """

    base_rate: Decimal = Decimal("0.15")
    floor_rate: Decimal = Decimal("0.1")
    maintenance_rate: Decimal = Decimal("0.075")

    def __post_init__(self) -> None:
        if min(self.base_rate, self.floor_rate, self.maintenance_rate) < 0:
            raise ValueError("the rates are not negative")

    @classmethod
    def from_table(cls, table: Mapping[str, Any]) -> Self:
        """The rates a venue profile's ``margin`` table sets, with a default for
        each rate it leaves out; ``ValueError`` when the table is invalid."""
        try:
            return cls(**{name: Decimal(str(rate)) for name, rate in table.items()})
        except (TypeError, ArithmeticError, ValueError) as error:
            raise ValueError(f"the margin setting is invalid: {error}") from error

    def initial_margin(self, holding: ContractHolding, quote: OptionQuote) -> Decimal:
        per_contract = self._initial(holding.contract, holding.quantity, quote)
        return _scaled(holding, per_contract)

    def maintenance_margin(
        self, holding: ContractHolding, quote: OptionQuote
    ) -> Decimal:
        return _scaled(holding, self._maintenance(holding.quantity, quote))

    def _initial(
        self, contract: CryptoOption, quantity: Decimal, quote: OptionQuote
    ) -> Decimal:
        if quantity > 0:
            return quote.mark
        short = max(self._cushion(contract, quote), self.floor_rate) + quote.mark
        if contract.option_kind == OptionKind.CALL:
            return short
        return max(short, self._maintenance(quantity, quote))

    def _maintenance(self, quantity: Decimal, quote: OptionQuote) -> Decimal:
        if quantity > 0:
            return quote.mark
        return self.maintenance_rate + quote.mark

    def _cushion(self, contract: CryptoOption, quote: OptionQuote) -> Decimal:
        return self.base_rate - _otm_amount(contract, quote.index) / quote.index


def _otm_amount(contract: CryptoOption, index: Decimal) -> Decimal:
    strike = Decimal(str(contract.strike_price))
    gap = strike - index if contract.option_kind == OptionKind.CALL else index - strike
    return max(Decimal(0), gap)


def _scaled(holding: ContractHolding, per_contract: Decimal) -> Decimal:
    multiplier = Decimal(str(holding.contract.multiplier))
    return abs(holding.quantity) * multiplier * per_contract
