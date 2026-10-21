from datetime import UTC, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
from nautilus_trader.model import (
    CryptoOption,
    IndexPriceUpdate,
    InstrumentId,
    MarkPriceUpdate,
)

from sbt2.core.assets.option.margin.rates import OptionQuote
from sbt2.core.market import index_id
from sbt2.data import Catalog, Window

_LOOKBACK = timedelta(days=1)


class NoMarkError(LookupError):
    pass


class _Track:
    """The prices of one instrument, looked up as of a time."""

    def __init__(self, frame: pd.DataFrame) -> None:
        prices = frame["price"] if "price" in frame else pd.Series(dtype=float)
        self._times = pd.DatetimeIndex(prices.index).as_unit("ns").asi8
        self._prices = prices.to_numpy()

    def at(self, ts: int) -> Decimal | None:
        """The last price at or before ``ts``, in nanoseconds."""
        slot = int(np.searchsorted(self._times, ts, side="right")) - 1
        return None if slot < 0 else Decimal(str(self._prices[slot]))


class OptionMarket:
    """The marks of the contracts and the index prices of a run, read from the
    catalog over the run's data window."""

    def __init__(self, catalog: Catalog, window: tuple[datetime, datetime]) -> None:
        self._catalog = catalog
        self._window = window
        self._tracks: dict[tuple[InstrumentId, type], _Track] = {}

    def quote(self, contract: CryptoOption, ts: int) -> OptionQuote:
        """The contract's mark and its underlying's index as of ``ts``;
        ``NoMarkError`` when either is not known yet."""
        mark = self._track(contract.id, MarkPriceUpdate).at(ts)
        index = self._track(index_id(contract), IndexPriceUpdate).at(ts)
        if mark is None or index is None:
            when = pd.Timestamp(ts, tz=UTC)
            raise NoMarkError(f"no mark or index price of {contract.id} as of {when}")
        return OptionQuote(mark, index)

    def _track(self, instrument_id: InstrumentId, kind: type) -> _Track:
        key = (instrument_id, kind)
        if key not in self._tracks:
            start, end = self._window
            window = Window(start - _LOOKBACK, end)
            self._tracks[key] = _Track(self._catalog.frame(instrument_id, kind, window))
        return self._tracks[key]
