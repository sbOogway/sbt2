from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence

from nautilus_trader.common import Cache
from nautilus_trader.model import CryptoOption, InstrumentId


class Chain(ABC):
    """The option contracts a strategy can pick from, as of now."""

    @abstractmethod
    def contracts(self) -> list[CryptoOption]:
        """The contracts alive now, by expiry, then strike, then kind."""
        ...


class CachedChain(Chain):
    """The chain of the contracts the run loaded, read from nautilus's cache."""

    def __init__(
        self,
        cache: Cache,
        now_ns: Callable[[], int],
        instrument_ids: Sequence[InstrumentId],
    ) -> None:
        self._cache = cache
        self._now_ns = now_ns
        self._instrument_ids = instrument_ids

    def contracts(self) -> list[CryptoOption]:
        now = self._now_ns()
        alive = [each for each in self._loaded() if _is_alive(each, now)]
        return sorted(alive, key=_order)

    def _loaded(self) -> list[CryptoOption]:
        found = (self._cache.instrument(each) for each in self._instrument_ids)
        return [each for each in found if isinstance(each, CryptoOption)]


def _is_alive(contract: CryptoOption, now: int) -> bool:
    return contract.activation_ns <= now < contract.expiration_ns


def _order(contract: CryptoOption) -> tuple[int, float, str]:
    return (
        contract.expiration_ns,
        float(contract.strike_price),
        contract.option_kind.name,
    )
