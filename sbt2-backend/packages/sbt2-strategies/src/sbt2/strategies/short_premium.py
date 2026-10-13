from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
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
    Strategy,
    short_strangle,
)


@dataclass(frozen=True)
class PremiumParams:
    """``dte`` is the days to expiry to open at. A combo closes at ``close_dte``
    days left, once it holds ``profit_target`` percent of its credit, or once it
    has lost ``loss_target`` percent of it; 0 sets no stop. A combo opens every
    ``interval_hours`` when none is held and the IV rank is within
    ``min_iv_rank`` and ``max_iv_rank``."""

    dte: float = 45
    close_dte: float = 21
    profit_target: Decimal = Decimal(50)
    loss_target: Decimal = Decimal(0)
    quantity: Decimal = Decimal(1)
    interval_hours: int = 24
    min_iv_rank: float = 0.0
    max_iv_rank: float = 1.0


@dataclass(frozen=True)
class StrangleParams(PremiumParams):
    delta: float = 0.16


class ShortPremium[P: PremiumParams](Strategy[P], ABC):
    """Sells one combo of options at a time: on each tick, when it holds none and
    the IV rank is within its band, it opens the combo ``build`` makes at the
    expiry nearest ``dte``; ``combo_exit`` closes it."""

    @classmethod
    @override
    def inputs(cls, params: P) -> Sequence[BarSpecification]:
        return ()

    @classmethod
    @override
    def schedule(cls, params: P) -> timedelta | None:
        return timedelta(hours=params.interval_hours)

    @classmethod
    @override
    def iv_lookback(cls, params: P) -> timedelta:
        return IV_LOOKBACK if _has_band(params) else timedelta(0)

    @classmethod
    @override
    def combo_exit(cls, params: P) -> ComboExit:
        stop = params.loss_target or None
        return ComboExit(params.close_dte, params.profit_target, stop)

    @abstractmethod
    def build(self, chain: Chain, expiry: datetime) -> Combo | None:
        """The combo to sell at ``expiry``; none when the chain lacks a leg."""
        ...

    @override
    def on_bar(self, bar: Bar) -> None:
        raise AssertionError("a short premium strategy reads no bars")

    @override
    def on_schedule(self, now: datetime) -> None:
        if self.combos or self.warming_up or not self._in_band():
            return
        expiry = self.chain.nearest_expiry(self.params.dte)
        combo = None if expiry is None else self.build(self.chain, expiry)
        if combo is not None:
            self.open_combo(combo)

    def _in_band(self) -> bool:
        if not _has_band(self.params):
            return True
        try:
            rank = self.chain.iv_rank()
        except NoMarketError:
            return False
        return self.params.min_iv_rank <= rank <= self.params.max_iv_rank


class ShortStrangle(ShortPremium[StrangleParams]):
    """Sells the put and the call nearest ``delta``."""

    Params = StrangleParams

    @override
    def build(self, chain: Chain, expiry: datetime) -> Combo | None:
        return _strangle(chain, expiry, self.params)


def _has_band(params: PremiumParams) -> bool:
    return params.min_iv_rank > 0 or params.max_iv_rank < 1


def _strangle(chain: Chain, expiry: datetime, params: StrangleParams) -> Combo | None:
    put = chain.nearest_delta(expiry, -params.delta)
    call = chain.nearest_delta(expiry, params.delta)
    if put is None or call is None:
        return None
    return short_strangle(put, call, params.quantity)
