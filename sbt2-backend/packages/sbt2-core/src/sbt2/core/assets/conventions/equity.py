from abc import ABC, abstractmethod

import pandas as pd
from nautilus_trader.common import Cache

CORRECTION_COLUMNS = ["ts_event", "currency", "amount"]


class EquityConvention(ABC):
    """How the equity nautilus reports differs from the true equity."""

    @abstractmethod
    def corrections(self, cache: Cache) -> pd.DataFrame:
        """What to add to the reported equity from each ``ts_event`` (in nanoseconds)
        on, as ``amount`` of ``currency``, until the next row of that currency."""
        ...


class NativeEquity(EquityConvention):
    """The equity nautilus reports is true."""

    def corrections(self, cache: Cache) -> pd.DataFrame:
        del cache
        return pd.DataFrame(columns=CORRECTION_COLUMNS)
