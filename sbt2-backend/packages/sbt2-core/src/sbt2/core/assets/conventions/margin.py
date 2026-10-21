from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

import pandas as pd
from nautilus_trader.common import Cache

from sbt2.core.assets.conventions.quotes import QuoteJob
from sbt2.core.market import Rates

MARGIN_COLUMNS = ["ts_event", "currency", "margin_used", "maintenance_margin"]


class MarginModel(ABC):
    """The margin of the positions of one run, in the settlement currency.

    ``quantity`` is signed, negative when short, and ``ts`` is in nanoseconds.
    """

    @abstractmethod
    def initial(self, instrument: Any, quantity: Decimal, ts: int) -> Decimal:
        """What a position of ``quantity`` contracts of ``instrument`` reserves,
        as of ``ts``."""
        ...

    @abstractmethod
    def maintenance(self, instrument: Any, quantity: Decimal, ts: int) -> Decimal:
        """What the position must keep reserved, as of ``ts``."""
        ...

    @abstractmethod
    def value(self, instrument: Any, quantity: Decimal, ts: int) -> Decimal:
        """What the position is worth at the mark as of ``ts``."""
        ...

    @abstractmethod
    def used(self, cache: Cache, grid: Sequence[int], rates: Rates) -> pd.DataFrame:
        """The margin the run's positions reserved at each time of ``grid``, in
        nanoseconds, as the ``MARGIN_COLUMNS`` hold: the ``margin_used`` and the
        ``maintenance_margin`` in the reporting currency of ``rates``, which
        convert the margin of the positions settled in other currencies. A fill
        counts from the next time on, as in the equity."""
        ...


class MarginConvention(ABC):
    """How the venue margins the positions of its instruments."""

    @abstractmethod
    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        """The venue arguments with the margin settings filled in with their
        defaults; ``ValueError`` when the settings are invalid."""
        ...

    @abstractmethod
    def model(self, job: QuoteJob) -> MarginModel | None:
        """The margin model of a run of ``job``; none when nautilus margins the
        run's positions."""
        ...


class NoMargin(MarginConvention):
    """Nautilus margins the positions."""

    def model(self, job: QuoteJob) -> MarginModel | None:
        del job
        return None

    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        if "margin" in venue:
            raise ValueError("this asset class takes no margin setting")
        return dict(venue)
