from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from typing import override

from nautilus_trader.model import Bar, BarSpecification

from sbt2.core.strategy import (
    IV_LOOKBACK,
    Chain,
    Combo,
    ComboExit,
    NoMarketError,
    RunConfig,
    ShortPremiumRules,
    Strategy,
)
from sbt2.strategies.premium_sizing import (
    contract_quantity,
    kelly_fraction,
    proportions,
    shared_fractions,
)
from sbt2.strategies.short_premium import (
    CondorParams,
    StrangleParams,
    condor,
    strangle,
)

ONE = Decimal(1)
ONE_UNDERLYING = [[1.0]]


@dataclass(frozen=True)
class PortfolioParams:
    """The core book sells strangles at ``core_delta``, the supplemental book iron
    condors at ``supplemental_delta`` with wings at ``wing_delta``, each at its
    DTE. A book holds ``ladder`` combos at once, one opened every
    ``dte / ladder`` days. A combo closes at ``close_dte`` days left, once it
    holds ``profit_target`` percent of its credit, or once it has lost
    ``loss_target`` percent of it; 0 sets no stop.

    The size of a book follows Equation 8.1 of the book from ``risk_free`` and its
    probability of profit; underlyings correlated at ``correlation_group`` or
    more share the larger fraction. The books split the share of the equity that
    the IV rank allows, between ``allocation_low`` at a rank of 0 and
    ``allocation_high`` at a rank of 1, as the rules of the spec do."""

    core_delta: float = 0.16
    core_dte: float = 45
    core_pop: float = 0.79
    supplemental_delta: float = 0.16
    wing_delta: float = 0.10
    supplemental_dte: float = 45
    supplemental_pop: float = 0.70
    ladder: int = 3
    close_dte: float = 21
    profit_target: Decimal = Decimal(50)
    loss_target: Decimal = Decimal(0)
    risk_free: float = 0.03
    correlation_group: float = 0.7
    allocation_low: Decimal = Decimal("0.25")
    allocation_high: Decimal = Decimal("0.50")
    interval_hours: int = 24


@dataclass(frozen=True)
class SubBook:
    """A group of combos of one kind: its days to expiry, its probability of profit
    and how to build one combo of unit size at an expiry."""

    name: str
    dte: float
    pop: float
    build: Callable[[Chain, datetime], Combo | None]


@dataclass(frozen=True)
class Held:
    """An open or opening combo: its book and expiry."""

    book: str
    expiry: datetime


class PremiumPortfolio(Strategy[PortfolioParams]):
    """Sells strangles (the core book) and iron condors (the supplemental book) on
    staggered expiries. Each new combo has a buying power reduction of its book's
    share of the allocation, over ``ladder``."""

    Params = PortfolioParams

    @classmethod
    @override
    def inputs(cls, params: PortfolioParams) -> Sequence[BarSpecification]:
        return ()

    @classmethod
    @override
    def schedule(cls, params: PortfolioParams) -> timedelta | None:
        return timedelta(hours=params.interval_hours)

    @classmethod
    @override
    def iv_lookback(cls, params: PortfolioParams) -> timedelta:
        return IV_LOOKBACK

    @classmethod
    @override
    def combo_exit(cls, params: PortfolioParams) -> ComboExit:
        stop = params.loss_target or None
        return ComboExit(params.close_dte, params.profit_target, stop)

    @override
    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        self._held: dict[str, Held] = {}
        self._last_opened: dict[str, datetime] = {}

    @override
    def on_bar(self, bar: Bar) -> None:
        raise AssertionError("a premium portfolio reads no bars")

    @override
    def on_schedule(self, now: datetime) -> None:
        if self.warming_up:
            return
        books = self._books()
        shares = self._shares(books)
        for book, share in zip(books, shares, strict=True):
            self._fill_ladder(book, share, now)

    @override
    def on_combo_closed(self, combo: Combo) -> None:
        self._held.pop(combo.id, None)

    @override
    def on_combo_settled(self, combo: Combo) -> None:
        self._held.pop(combo.id, None)

    @override
    def on_combo_failed(self, combo: Combo, reason: str) -> None:
        self._held.pop(combo.id, None)

    def _books(self) -> list[SubBook]:
        params = self.params
        core = StrangleParams(delta=params.core_delta, quantity=ONE)
        body = CondorParams(
            delta=params.supplemental_delta, wing_delta=params.wing_delta, quantity=ONE
        )
        return [
            SubBook(
                "core",
                params.core_dte,
                params.core_pop,
                lambda chain, expiry: strangle(chain, expiry, core),
            ),
            SubBook(
                "supplemental",
                params.supplemental_dte,
                params.supplemental_pop,
                lambda chain, expiry: condor(chain, expiry, body),
            ),
        ]

    def _shares(self, books: list[SubBook]) -> list[float]:
        fractions = [
            shared_fractions(
                [kelly_fraction(self.params.risk_free, book.dte, book.pop)],
                ONE_UNDERLYING,
                self.params.correlation_group,
            )[0]
            for book in books
        ]
        return proportions(fractions)

    def _fill_ladder(self, book: SubBook, share: float, now: datetime) -> None:
        held = [each.expiry for each in self._held.values() if each.book == book.name]
        if len(held) >= self.params.ladder or not self._is_due(book, now):
            return
        expiry = self.chain.nearest_expiry(book.dte)
        if expiry is None or expiry in held:
            return
        combo = self._sized(book, expiry, share)
        if combo is None:
            return
        opened = self.open_combo(combo)
        if opened.id:
            self._held[opened.id] = Held(book.name, expiry)
            self._last_opened[book.name] = now

    def _is_due(self, book: SubBook, now: datetime) -> bool:
        last = self._last_opened.get(book.name)
        return last is None or now - last >= timedelta(
            days=book.dte / self.params.ladder
        )

    def _sized(self, book: SubBook, expiry: datetime, share: float) -> Combo | None:
        unit = book.build(self.chain, expiry)
        if unit is None:
            return None
        try:
            one_contract = self.margin_of_combo(unit)
            target = self._target(unit, share)
        except LookupError:
            return None
        if one_contract <= 0:
            return None
        step = unit.legs[0].contract.size_increment.as_decimal()
        quantity = contract_quantity(target, one_contract, step)
        return _scaled(unit, quantity) if quantity > 0 else None

    def _target(self, unit: Combo, share: float) -> Decimal:
        contract = unit.legs[0].contract
        account = self.portfolio.account(contract.id.venue)
        if account is None:
            raise RuntimeError("the run has no account")
        equity = account.balance_total(contract.settlement_currency).as_decimal()
        band = (self.params.allocation_low, self.params.allocation_high)
        rules = ShortPremiumRules(band)
        allocation = rules.allocation_at(self._iv_rank())
        return Decimal(str(share)) * allocation * equity / self.params.ladder

    def _iv_rank(self) -> float | None:
        try:
            return self.chain.iv_rank()
        except NoMarketError:
            return None


def _scaled(unit: Combo, quantity: Decimal) -> Combo:
    return replace(
        unit,
        legs=tuple(replace(leg, quantity=leg.quantity * quantity) for leg in unit.legs),
    )
