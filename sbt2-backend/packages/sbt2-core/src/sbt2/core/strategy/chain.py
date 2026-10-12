from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from nautilus_trader.core import dt_to_unix_nanos, unix_nanos_to_dt
from nautilus_trader.model import CryptoOption, InstrumentId, OptionKind, QuoteTick

from sbt2.core.strategy.chain_records import ChainRecords
from sbt2.core.strategy.greeks import Greeks, Market, greeks_of

_DAY_NS = 86_400 * 10**9


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
