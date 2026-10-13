from datetime import datetime, timedelta
from decimal import Decimal
from typing import ClassVar, override

from combo_strategies import LADDER_EXPIRY
from nautilus_trader.model import CryptoOption, OptionKind
from run_strategies import OnSchedule

from sbt2.core.strategy import (
    IV_LOOKBACK,
    Chain,
    ChainFilter,
    Combo,
    NoParams,
    short_strangle,
)
from sbt2.core.strategy.chain import MultipleChainsError


class ReadChains(OnSchedule):
    """Notes, at each tick, the underlyings of the contracts of each chain."""

    seen: ClassVar[dict[datetime, dict[str, set[str]]]] = {}

    @override
    def on_schedule(self, now: datetime) -> None:
        self.seen[now] = {
            code: {each.underlying.code for each in chain.contracts()}
            for code, chain in self.chains.items()
        }


class ReadTheChain(OnSchedule):
    """Asks for ``chain`` at each tick and notes the error it raises."""

    errors: ClassVar[list[str]] = []

    @override
    def on_schedule(self, now: datetime) -> None:
        try:
            _ = self.chain
        except MultipleChainsError as error:
            self.errors.append(str(error))


class ReadChainRanks(OnSchedule):
    """Notes the IV rank of each chain at each tick."""

    ranks: ClassVar[dict[datetime, dict[str, float]]] = {}

    @classmethod
    @override
    def iv_lookback(cls, params: NoParams) -> timedelta:
        return IV_LOOKBACK

    @override
    def on_schedule(self, now: datetime) -> None:
        self.ranks[now] = {code: chain.iv_rank() for code, chain in self.chains.items()}


class OpenBothStrangles(OnSchedule):
    """Opens a short strangle of 12 January on each chain, on the first tick
    after warm-up, and notes the balance of each coin when each combo is open."""

    opened: ClassVar[list[Combo]] = []
    balances: ClassVar[list[dict[str, Decimal]]] = []
    strikes: ClassVar[dict[str, tuple[int, int]]] = {
        "BTC": (40000, 50000),
        "ETH": (2000, 3000),
    }

    @classmethod
    def clear(cls) -> None:
        cls.opened.clear()
        cls.balances.clear()

    @override
    def on_start(self) -> None:
        super().on_start()
        self.placed = False

    @override
    def on_schedule(self, now: datetime) -> None:
        if self.placed or self.warming_up:
            return
        self.placed = True
        for code, chain in self.chains.items():
            self.open_combo(self.strangle(chain, *self.strikes[code]))

    def strangle(self, chain: Chain, put: int, call: int) -> Combo:
        return short_strangle(
            self.contract(chain, OptionKind.PUT, put),
            self.contract(chain, OptionKind.CALL, call),
            Decimal(1),
        )

    def contract(self, chain: Chain, kind: OptionKind, strike: int) -> CryptoOption:
        [found] = chain.contracts(
            ChainFilter(kind=kind, strikes=(strike, strike), expiry=LADDER_EXPIRY)
        )
        return found

    @override
    def on_combo_opened(self, combo: Combo) -> None:
        self.opened.append(combo)
        account = self.portfolio.account(combo.legs[0].contract.id.venue)
        assert account is not None
        self.balances.append(
            {
                money.currency.code: money.as_decimal()
                for money in account.balances_total().values()
            }
        )


class OpenBothWithHistory(OpenBothStrangles):
    """Like ``OpenBothStrangles``, with a year of index prices before its data."""

    @classmethod
    @override
    def iv_lookback(cls, params: NoParams) -> timedelta:
        return IV_LOOKBACK


class MeasureMargins(OpenBothStrangles):
    """Notes, at each tick, the initial margin of the positions of each coin."""

    margins: ClassVar[dict[datetime, dict[str, Decimal]]] = {}

    @override
    def on_schedule(self, now: datetime) -> None:
        super().on_schedule(now)
        held: dict[str, Decimal] = {}
        for instrument_id, margin in self.margin_of_positions().items():
            code = instrument_id.symbol.value.partition("-")[0]
            held[code] = held.get(code, Decimal(0)) + margin
        self.margins[now] = held


class TradeBothStrangles(OpenBothStrangles):
    """Closes both strangles on the tick after they opened."""

    @override
    def on_schedule(self, now: datetime) -> None:
        super().on_schedule(now)
        for combo in self.combos:
            self.close_combo(combo)
