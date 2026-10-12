from datetime import UTC, datetime
from decimal import Decimal
from typing import ClassVar, override

from nautilus_trader.model import CryptoOption, MarketOrder, OptionKind
from run_strategies import OnSchedule

from sbt2.core.strategy import (
    ChainFilter,
    Combo,
    ComboExit,
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

    @override
    def on_combo_closed(self, combo: Combo) -> None:
        self.closed.append(combo)

    @override
    def on_combo_settled(self, combo: Combo) -> None:
        self.settled.append(combo)

    @override
    def on_margin_refused(self, order: MarketOrder, reason: str) -> None:
        self.refused.append(str(order.instrument_id))


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
