"""A chain over contracts held in memory, for tests that need no run."""

from collections.abc import Callable, Collection
from datetime import datetime

from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import CryptoOption, InstrumentId, Price, Quantity, QuoteTick

from sbt2.core.strategy import CachedChain, ChainRecords


def ns(moment: datetime) -> int:
    return dt_to_unix_nanos(moment)


def clock(moment: datetime) -> Callable[[], int]:
    return lambda: ns(moment)


class FakeCache:
    """Holds ``contracts``; each has a quote unless its id is in ``unquoted``."""

    def __init__(
        self, contracts: tuple[CryptoOption, ...], unquoted: Collection[InstrumentId]
    ) -> None:
        self._contracts = {each.id: each for each in contracts}
        self._unquoted = unquoted

    def instrument(self, instrument_id: InstrumentId, /) -> CryptoOption | None:
        return self._contracts.get(instrument_id)

    def quote(self, instrument_id: InstrumentId, /) -> QuoteTick | None:
        if instrument_id in self._unquoted:
            return None
        price, size = Price.from_str("0.0500"), Quantity.from_str("1.0")
        return QuoteTick(instrument_id, price, price, size, size, 0, 0)


def chain_of(
    records: ChainRecords,
    *contracts: CryptoOption,
    unquoted: Collection[InstrumentId] = (),
) -> CachedChain:
    cache = FakeCache(contracts, unquoted)
    return CachedChain(cache, [each.id for each in contracts], records)
