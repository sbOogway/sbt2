from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, override

from nautilus_trader.core import unix_nanos_to_dt
from nautilus_trader.model import Bar, BarSpecification, CryptoOption, OptionKind

from sbt2.core.strategy import (
    IV_LOOKBACK,
    Chain,
    ChainFilter,
    Combo,
    ComboExit,
    NoMarketError,
    Strategy,
    iron_condor,
    short_put,
    short_straddle,
    short_strangle,
    vertical_spread,
)

AT_THE_MONEY = 0.5


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


@dataclass(frozen=True)
class CondorParams(StrangleParams):
    wing_delta: float = 0.10


@dataclass(frozen=True)
class SpreadParams(CondorParams):
    side: Literal["put", "call"] = "put"


@dataclass(frozen=True)
class RegimeParams(CondorParams):
    iv_rank_threshold: float = 0.5


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
        return strangle(chain, expiry, self.params)


class ShortStraddle(ShortPremium[PremiumParams]):
    """Sells the put and the call at the money, of one strike."""

    Params = PremiumParams

    @override
    def build(self, chain: Chain, expiry: datetime) -> Combo | None:
        call = chain.nearest_delta(expiry, AT_THE_MONEY)
        put = None if call is None else _put_at(chain, call)
        if call is None or put is None:
            return None
        return short_straddle(put, call, self.params.quantity)


class IronCondor(ShortPremium[CondorParams]):
    """Sells the strangle nearest ``delta`` and buys the wings nearest
    ``wing_delta``."""

    Params = CondorParams

    @override
    def build(self, chain: Chain, expiry: datetime) -> Combo | None:
        return condor(chain, expiry, self.params)


class VerticalSpread(ShortPremium[SpreadParams]):
    """Sells the contract nearest ``delta`` and buys the one nearest
    ``wing_delta``, both puts or both calls by ``side``."""

    Params = SpreadParams

    @override
    def build(self, chain: Chain, expiry: datetime) -> Combo | None:
        sign = -1 if self.params.side == "put" else 1
        short = chain.nearest_delta(expiry, sign * self.params.delta)
        long = chain.nearest_delta(expiry, sign * self.params.wing_delta)
        if short is None or long is None or not _is_beyond(long, short):
            return None
        return vertical_spread(short, long, self.params.quantity)


class ShortPut(ShortPremium[StrangleParams]):
    """Sells the put nearest ``delta``."""

    Params = StrangleParams

    @override
    def build(self, chain: Chain, expiry: datetime) -> Combo | None:
        put = chain.nearest_delta(expiry, -self.params.delta)
        return None if put is None else short_put(put, self.params.quantity)


class IvRegime(ShortPremium[RegimeParams]):
    """Sells an iron condor while the IV rank is below ``iv_rank_threshold``, and
    a strangle, which has no defined risk, from the threshold up."""

    Params = RegimeParams

    @classmethod
    @override
    def iv_lookback(cls, params: RegimeParams) -> timedelta:
        return IV_LOOKBACK

    @override
    def build(self, chain: Chain, expiry: datetime) -> Combo | None:
        try:
            rank = chain.iv_rank()
        except NoMarketError:
            return None
        if rank < self.params.iv_rank_threshold:
            return condor(chain, expiry, self.params)
        return strangle(chain, expiry, self.params)


def _has_band(params: PremiumParams) -> bool:
    return params.min_iv_rank > 0 or params.max_iv_rank < 1


def strangle(chain: Chain, expiry: datetime, params: StrangleParams) -> Combo | None:
    """The short strangle nearest ``params.delta`` at ``expiry``, if the chain has
    both legs."""
    put = chain.nearest_delta(expiry, -params.delta)
    call = chain.nearest_delta(expiry, params.delta)
    if put is None or call is None:
        return None
    return short_strangle(put, call, params.quantity)


def condor(chain: Chain, expiry: datetime, params: CondorParams) -> Combo | None:
    """The iron condor of ``params`` at ``expiry``, if the chain has its legs and
    the wings lie beyond the body."""
    body = strangle(chain, expiry, params)
    put_wing = chain.nearest_delta(expiry, -params.wing_delta)
    call_wing = chain.nearest_delta(expiry, params.wing_delta)
    if body is None or put_wing is None or call_wing is None:
        return None
    [put, call] = (leg.contract for leg in body.legs)
    if not (_is_beyond(put_wing, put) and _is_beyond(call_wing, call)):
        return None
    return iron_condor(body, put_wing, call_wing)


def _put_at(chain: Chain, call: CryptoOption) -> CryptoOption | None:
    strike = float(call.strike_price)
    found = chain.contracts(
        ChainFilter(
            kind=OptionKind.PUT,
            strikes=(strike, strike),
            expiry=unix_nanos_to_dt(call.expiration_ns),
        )
    )
    return found[0] if found else None


def _is_beyond(wing: CryptoOption, short: CryptoOption) -> bool:
    """Whether ``wing`` is further out of the money than ``short``."""
    if short.option_kind == OptionKind.PUT:
        return float(wing.strike_price) < float(short.strike_price)
    return float(wing.strike_price) > float(short.strike_price)
