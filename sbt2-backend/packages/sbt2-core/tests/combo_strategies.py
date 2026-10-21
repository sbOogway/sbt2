from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar, override

from nautilus_trader.model import (
    CryptoOption,
    InstrumentId,
    MarketOrder,
    OptionKind,
    OrderSide,
)
from option_catalog import Terms, chain_contract_id, listed_option
from run_strategies import OnSchedule

from sbt2.core.strategy import (
    ChainFilter,
    Combo,
    ComboExit,
    Leg,
    NoParams,
    short_straddle,
    short_strangle,
)

LADDER_EXPIRY = datetime(2024, 1, 12, 8, tzinfo=UTC)
CHAIN_EXPIRY = datetime(2024, 1, 2, 8, tzinfo=UTC)


class OpenStrangle(OnSchedule):
    """Opens a short strangle of 12 January on its first tick after warm-up, and
    notes the combos it hears about and their P/L in percent at each tick."""

    quantity = Decimal(1)
    expiry = LADDER_EXPIRY
    opened: ClassVar[list[Combo]] = []
    closed: ClassVar[list[Combo]] = []
    settled: ClassVar[list[Combo]] = []
    refused: ClassVar[list[str]] = []
    percents: ClassVar[list[tuple[datetime, Decimal]]] = []
    seen: ClassVar[list[tuple[datetime, tuple[str, ...]]]] = []
    margins: ClassVar[list[tuple[Decimal, Decimal]]] = []
    failed: ClassVar[list[tuple[Combo, str]]] = []
    reasons: ClassVar[list[str]] = []
    declined: ClassVar[list[tuple[Combo, str]]] = []
    balances: ClassVar[list[Decimal]] = []

    @classmethod
    def clear(cls) -> None:
        for each in (
            cls.opened,
            cls.closed,
            cls.settled,
            cls.refused,
            cls.percents,
            cls.seen,
            cls.margins,
            cls.failed,
            cls.reasons,
            cls.declined,
            cls.balances,
        ):
            each.clear()

    @override
    def on_start(self) -> None:
        super().on_start()
        self.placed = False

    @override
    def on_schedule(self, now: datetime) -> None:
        if not self.placed and not self.warming_up:
            self.placed = True
            self.open_combo(self.combo())
        self.seen.append((now, tuple(each.id for each in self.combos)))
        for combo in self.combos:
            self.percents.append((now, combo.pl_percent(self.chain.quote)))

    def combo(self) -> Combo:
        return short_strangle(
            self.contract(OptionKind.PUT, 40000),
            self.contract(OptionKind.CALL, 50000),
            self.quantity,
        )

    def contract(self, kind: OptionKind, strike: int) -> CryptoOption:
        [found] = self.chain.contracts(
            ChainFilter(kind=kind, strikes=(strike, strike), expiry=self.expiry)
        )
        return found

    @override
    def on_combo_opened(self, combo: Combo) -> None:
        self.opened.append(combo)
        held = sum(self.margin_of_positions().values(), Decimal(0))
        self.margins.append((self.margin_of_combo(combo), held))
        [leg, *_] = combo.legs
        account = self.portfolio.account(leg.contract.id.venue)
        assert account is not None
        self.balances.append(
            account.balance_total(leg.contract.settlement_currency).as_decimal()
        )

    @override
    def on_combo_closed(self, combo: Combo) -> None:
        self.closed.append(combo)

    @override
    def on_combo_settled(self, combo: Combo) -> None:
        self.settled.append(combo)

    @override
    def on_combo_failed(self, combo: Combo, reason: str) -> None:
        self.failed.append((combo, reason))

    @override
    def on_combo_refused(self, combo: Combo, reason: str) -> None:
        self.declined.append((combo, reason))

    @override
    def on_margin_refused(self, order: MarketOrder, reason: str) -> None:
        self.refused.append(str(order.instrument_id))
        self.reasons.append(reason)


class OpenTenStrangles(OpenStrangle):
    """Opens a strangle of ten, more than 1 BTC of capital can margin."""

    quantity = Decimal(10)


class CloseStrangleAtOnce(OpenStrangle):
    """Closes its strangle on the first tick after it opened."""

    @override
    def on_schedule(self, now: datetime) -> None:
        super().on_schedule(now)
        for combo in self.combos:
            self.close_combo(combo)


class CloseStrangleAtProfit(OpenStrangle):
    @classmethod
    @override
    def combo_exit(cls, params: NoParams) -> ComboExit:
        return ComboExit(profit_target=Decimal(20))


class CloseStrangleAtLoss(OpenStrangle):
    @classmethod
    @override
    def combo_exit(cls, params: NoParams) -> ComboExit:
        return ComboExit(loss_target=Decimal(20))


class CloseStrangleAtDte(OpenStrangle):
    @classmethod
    @override
    def combo_exit(cls, params: NoParams) -> ComboExit:
        return ComboExit(dte=9.5)


class HoldStraddleToExpiry(OpenStrangle):
    """Opens a short straddle of 2 January that expires in the run."""

    expiry = CHAIN_EXPIRY

    @override
    def combo(self) -> Combo:
        return short_straddle(
            self.contract(OptionKind.PUT, 45000),
            self.contract(OptionKind.CALL, 45000),
            self.quantity,
        )


class OpenStrangleWithExpiredCall(OpenStrangle):
    """Opens a strangle on 3 January whose call, of 2 January, has expired: the
    venue rejects its order after the other leg filled."""

    expiry = datetime(2024, 1, 12, 8, tzinfo=UTC)

    @override
    def on_schedule(self, now: datetime) -> None:
        if now >= datetime(2024, 1, 3, tzinfo=UTC):
            super().on_schedule(now)

    @override
    def combo(self) -> Combo:
        expired = self.cache.instrument(chain_contract_id("2JAN24", 45000, "C"))
        assert isinstance(expired, CryptoOption)
        legs = (self.contract(OptionKind.PUT, 45000), expired)
        return Combo(
            "short strangle",
            tuple(Leg(each, OrderSide.SELL, self.quantity) for each in legs),
        )


class OpenStrangleWithUnknownCall(OpenStrangle):
    """Opens a strangle whose call is no contract of the run."""

    @override
    def combo(self) -> Combo:
        unknown = listed_option(
            InstrumentId.from_str("BTC-12JAN24-52000-C.DERIBIT"),
            Terms(OptionKind.CALL, LADDER_EXPIRY, "52000"),
        )
        legs = (self.contract(OptionKind.PUT, 40000), unknown)
        return Combo(
            "short strangle",
            tuple(Leg(each, OrderSide.SELL, self.quantity) for each in legs),
        )


class TwoTrades(OpenStrangle):
    """Opens a strangle and then a straddle, one tick apart. The strangle closes at
    its DTE rule; the straddle closes by hand three ticks after it opened."""

    @classmethod
    @override
    def combo_exit(cls, params: NoParams) -> ComboExit:
        return ComboExit(dte=9.5)

    @override
    def on_start(self) -> None:
        super().on_start()
        self.ticks = 0

    @override
    def on_schedule(self, now: datetime) -> None:
        if self.warming_up:
            return
        self.ticks += 1
        if self.ticks == 1:
            self.open_combo(self.combo())
        if self.ticks == 2:
            self.open_combo(self.straddle())
        if self.ticks == 5:
            for combo in self.combos:
                if combo.name == "short straddle":
                    self.close_combo(combo)

    def straddle(self) -> Combo:
        return short_straddle(
            self.contract(OptionKind.PUT, 45000),
            self.contract(OptionKind.CALL, 45000),
            self.quantity,
        )


class HoldOppositeStraddles(HoldStraddleToExpiry):
    """Opens a long straddle of ``long`` and a short straddle of ``short`` on the
    contracts of 2 January, one tick apart, and holds both to expiry."""

    long = Decimal(2)
    short = Decimal(1)

    @override
    def on_start(self) -> None:
        super().on_start()
        self.ticks = 0

    @override
    def on_schedule(self, now: datetime) -> None:
        if not self.warming_up:
            self.ticks += 1
            self.placed = True
        if self.ticks == 1:
            self.open_combo(self.straddle(OrderSide.BUY, self.long))
        if self.ticks == 2:
            self.open_combo(self.straddle(OrderSide.SELL, self.short))
        super().on_schedule(now)

    def straddle(self, side: OrderSide, quantity: Decimal) -> Combo:
        legs = (
            self.contract(OptionKind.PUT, 45000),
            self.contract(OptionKind.CALL, 45000),
        )
        return Combo("straddle", tuple(Leg(each, side, quantity) for each in legs))
