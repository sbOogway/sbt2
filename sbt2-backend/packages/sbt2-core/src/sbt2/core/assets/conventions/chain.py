from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nautilus_trader.model import InstrumentId

from sbt2.core.market import ChainFeeds
from sbt2.data import Catalog, Selection


@dataclass(frozen=True)
class ChainJob:
    """The chain ``chain`` names, bounded by the bands of ``table``: the contracts
    the ``catalog`` holds that live in ``window``."""

    catalog: Catalog
    chain: InstrumentId
    window: tuple[datetime, datetime]
    table: Mapping[str, Any]


class ChainConvention(ABC):
    """Whether an instrument names a whole chain of contracts, which the run
    loads while it goes."""

    @abstractmethod
    def names_chain(self, instrument_id: InstrumentId) -> bool:
        """Whether ``instrument_id`` names a chain instead of one instrument."""
        ...

    @abstractmethod
    def complete(self, table: Mapping[str, Any]) -> dict[str, Any]:
        """The spec's chain table with the defaults filled in; ``ValueError``
        when it is invalid."""
        ...

    @abstractmethod
    def contracts(self, job: ChainJob) -> list[InstrumentId]:
        """The ids of the contracts of the chain that are alive in the window and
        inside the bands at some time."""
        ...

    @abstractmethod
    def days(self, chain: InstrumentId, window: tuple[datetime, datetime]) -> Selection:
        """The data whose days tell which days of ``window`` the catalog holds of
        the chain."""
        ...

    @abstractmethod
    def references(
        self, chain: InstrumentId, window: tuple[datetime, datetime]
    ) -> list[Selection]:
        """The series besides the contracts that a run of the chain reads."""
        ...

    @abstractmethod
    def feeds(self, chain: InstrumentId) -> ChainFeeds:
        """The series the strategy hears of the chain."""
        ...


class NoChain(ChainConvention):
    """No instrument names a chain."""

    def names_chain(self, instrument_id: InstrumentId) -> bool:
        del instrument_id
        return False

    def complete(self, table: Mapping[str, Any]) -> dict[str, Any]:
        if table:
            raise ValueError("this asset class takes no chain setting")
        return {}

    def contracts(self, job: ChainJob) -> list[InstrumentId]:
        del job
        return []

    def days(self, chain: InstrumentId, window: tuple[datetime, datetime]) -> Selection:
        del window
        raise LookupError(f"{chain} is not a chain")

    def references(
        self, chain: InstrumentId, window: tuple[datetime, datetime]
    ) -> list[Selection]:
        del chain, window
        return []

    def feeds(self, chain: InstrumentId) -> ChainFeeds:
        raise LookupError(f"{chain} is not a chain")
