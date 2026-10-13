from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from nautilus_trader.core import dt_to_unix_nanos, unix_nanos_to_dt
from nautilus_trader.model import CryptoOption, InstrumentId, OptionKind, QuoteTick

from sbt2.core.strategy.chain_records import ChainRecords
from sbt2.core.strategy.greeks import Greeks, Market, greeks_of

_DAY_NS = 86_400 * 10**9
IV_LOOKBACK = timedelta(days=365)
_MIN_DVOL_VALUES = 2


@dataclass(frozen=True)
class ChainFilter:
    """What a contract must match: its ``kind``, its days to expiry ``dte`` and its
    ``strikes``, both as inclusive ``(low, high)`` ranges, and its exact
    ``expiry``. A bound left out matches every contract."""

    kind: OptionKind | None = None
    dte: tuple[float, float] | None = None
    strikes: tuple[float, float] | None = None
    expiry: datetime | None = None


class NoMarketError(LookupError):
    """The chain has not heard the IV or the index price a question needs."""


class MultipleChainsError(LookupError):
    """``chain`` was asked in a run that streams several chains."""


class Chain(ABC):
    """The option contracts a strategy can pick from, as of now."""

    @abstractmethod
    def contracts(self, where: ChainFilter | None = None) -> list[CryptoOption]:
        """The contracts alive now that match ``where``, by expiry, then strike,
        then kind."""
        ...

    @abstractmethod
    def expiries(self) -> list[datetime]:
        """The expiries of the contracts alive now, earliest first."""
        ...

    @abstractmethod
    def quote(self, contract: CryptoOption) -> QuoteTick | None:
        """The latest quote of ``contract``; none before its first."""
        ...

    @abstractmethod
    def nearest_expiry(self, dte: float) -> datetime | None:
        """The expiry alive now whose days to expiry are nearest ``dte``, the
        earlier one on a tie; none on an empty chain."""
        ...

    @abstractmethod
    def nearest_delta(self, expiry: datetime, delta: float) -> CryptoOption | None:
        """The contract of ``expiry`` whose delta is nearest ``delta``, the lower
        strike on a tie. A call has a positive delta and a put a negative one,
        so ``delta`` picks the kind; ``ValueError`` for 0. A contract with no
        quote or no IV yet is passed over; none when no contract is left."""
        ...

    @abstractmethod
    def iv_rank(self, lookback: timedelta = IV_LOOKBACK) -> float:
        """Where DVOL stands now between its lowest and highest value over
        ``lookback``, from 0 to 1. ``NoMarketError`` when the chain heard fewer than
        two values in that span, or all of them are equal. The strategy sets how
        far back the run loads DVOL with ``iv_lookback``."""
        ...

    @abstractmethod
    def iv_percentile(self, lookback: timedelta = IV_LOOKBACK) -> float:
        """The share of the hourly DVOL values over ``lookback`` that are below
        the current one, from 0 to 1; ``NoMarketError`` when the chain heard fewer
        than two values in that span."""
        ...

    @abstractmethod
    def iv(self, contract: CryptoOption) -> float:
        """The latest implied volatility of ``contract`` as a fraction, Deribit's
        own; ``NoMarketError`` before its first."""
        ...

    @abstractmethod
    def greeks(self, contract: CryptoOption) -> Greeks:
        """The Black-Scholes greeks of ``contract`` now, from its IV and the latest
        index price; ``NoMarketError`` when either is not heard yet."""
        ...


class ChainCache(Protocol):
    """What the chain reads of nautilus's cache."""

    def instrument(self, instrument_id: InstrumentId, /) -> Any: ...

    def quote(self, instrument_id: InstrumentId, /) -> QuoteTick | None: ...


class CachedChain(Chain):
    """The chain of the contracts the run loaded, read from nautilus's cache."""

    def __init__(
        self,
        cache: ChainCache,
        instrument_ids: Sequence[InstrumentId],
        records: ChainRecords,
    ) -> None:
        self._cache = cache
        self._instrument_ids = instrument_ids
        self._records = records

    def contracts(self, where: ChainFilter | None = None) -> list[CryptoOption]:
        now = self._records.now_ns()
        matching = [
            each
            for each in self._loaded()
            if _is_alive(each, now) and _matches(each, where or ChainFilter(), now)
        ]
        return sorted(matching, key=_order)

    def expiries(self) -> list[datetime]:
        expiries = {each.expiration_ns for each in self.contracts()}
        return [unix_nanos_to_dt(each) for each in sorted(expiries)]

    def quote(self, contract: CryptoOption) -> QuoteTick | None:
        return self._cache.quote(contract.id)

    def nearest_expiry(self, dte: float) -> datetime | None:
        now = self._records.now_ns()
        return min(
            self.expiries(),
            key=lambda each: abs((dt_to_unix_nanos(each) - now) / _DAY_NS - dte),
            default=None,
        )

    def nearest_delta(self, expiry: datetime, delta: float) -> CryptoOption | None:
        if delta == 0:
            raise ValueError("a delta is above 0 for a call and below 0 for a put")
        kind = OptionKind.CALL if delta > 0 else OptionKind.PUT
        offered = self.contracts(ChainFilter(kind=kind, expiry=expiry))
        return min(
            (each for each in offered if self._is_priced(each)),
            key=lambda each: abs(self.greeks(each).delta - delta),
            default=None,
        )

    def iv_rank(self, lookback: timedelta = IV_LOOKBACK) -> float:
        values = self._volatility(lookback)
        low, high = min(values), max(values)
        if low == high:
            raise NoMarketError("DVOL did not move over the look-back")
        return (values[-1] - low) / (high - low)

    def iv_percentile(self, lookback: timedelta = IV_LOOKBACK) -> float:
        values = self._volatility(lookback)
        return sum(each < values[-1] for each in values) / len(values)

    def iv(self, contract: CryptoOption) -> float:
        found = self._records.iv(contract.id)
        if found is None:
            raise NoMarketError(f"{contract.id} has no IV yet")
        return found

    def greeks(self, contract: CryptoOption) -> Greeks:
        now = self._records.now_ns()
        index = self._records.index()
        if index is None:
            raise NoMarketError("the chain has heard no index price yet")
        return greeks_of(contract, Market(index, self.iv(contract)), now)

    def _volatility(self, lookback: timedelta) -> list[float]:
        since = (
            self._records.now_ns() - int(lookback / timedelta(microseconds=1)) * 1_000
        )
        values = self._records.volatility(since)
        if len(values) < _MIN_DVOL_VALUES:
            raise NoMarketError(
                f"the chain heard {len(values)} DVOL values over the look-back "
                "and needs two"
            )
        return values

    def _is_priced(self, contract: CryptoOption) -> bool:
        has_iv = self._records.iv(contract.id) is not None
        return has_iv and self.quote(contract) is not None

    def _loaded(self) -> list[CryptoOption]:
        found = (self._cache.instrument(each) for each in self._instrument_ids)
        return [each for each in found if isinstance(each, CryptoOption)]


def _is_alive(contract: CryptoOption, now: int) -> bool:
    return contract.activation_ns <= now < contract.expiration_ns


def _matches(contract: CryptoOption, where: ChainFilter, now: int) -> bool:
    return (
        _is(contract.option_kind, where.kind)
        and _within((contract.expiration_ns - now) / _DAY_NS, where.dte)
        and _within(float(contract.strike_price), where.strikes)
        and _is(contract.expiration_ns, _nanos(where.expiry))
    )


def _is[T](value: T, wanted: T | None) -> bool:
    return wanted is None or value == wanted


def _within(value: float, bounds: tuple[float, float] | None) -> bool:
    return bounds is None or bounds[0] <= value <= bounds[1]


def _nanos(moment: datetime | None) -> int | None:
    return None if moment is None else dt_to_unix_nanos(moment)


def _order(contract: CryptoOption) -> tuple[int, float, str]:
    return (
        contract.expiration_ns,
        float(contract.strike_price),
        contract.option_kind.name,
    )
