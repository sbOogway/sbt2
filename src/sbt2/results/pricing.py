from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import cached_property

import pandas as pd
from nautilus_trader.model import InstrumentId

from sbt2.data import Catalog, Gap, Selection, Window
from sbt2.results.metrics import RunTables, Segment
from sbt2.spec import ResolvedRunSpec


class MissingPricesError(LookupError):
    pass


@dataclass(frozen=True)
class Market:
    """The catalog a run is priced from, with the days the run skipped.

    Each instrument's prices of a type are read from the catalog once.
    """

    run: ResolvedRunSpec
    catalog: Catalog
    known_gaps: frozenset[Gap]
    _read: dict[tuple[InstrumentId, type], pd.Series] = field(
        default_factory=dict, init=False, repr=False, compare=False
    )

    @cached_property
    def grid(self) -> pd.DatetimeIndex:
        return Segment.of_run(self.run).grid

    @property
    def window(self) -> Window:
        return Window(self.run.start, self.run.end)

    def prices(self, instrument: InstrumentId, price_type: type) -> pd.Series:
        """The instrument's ``price_type`` on the grid, carried across known gaps.

        Grid times before the first price take that first price.
        """
        key = (instrument, price_type)
        if key not in self._read:
            self._read[key] = self._read_prices(instrument, price_type)
        return self._read[key]

    def _read_prices(self, instrument: InstrumentId, price_type: type) -> pd.Series:
        self._check_coverage(instrument, price_type)
        frame = self.catalog.frame(instrument, price_type, self.window)
        if frame.empty:
            raise _no_prices(instrument, price_type, self.window.days)
        return on_grid(pd.Series(frame["price"]), self.grid).bfill()

    def _check_coverage(self, instrument: InstrumentId, price_type: type) -> None:
        selection = Selection((instrument,), (price_type,), self.window)
        [coverage] = self.catalog.coverage(selection, self.known_gaps)
        if coverage.missing:
            raise _no_prices(instrument, price_type, coverage.missing)


@dataclass(frozen=True)
class PricedRun:
    """A stored run with the catalog its positions are valued from.

    Prices are carried across ``known_gaps``, the days the run skipped.
    """

    spec: ResolvedRunSpec
    tables: RunTables
    catalog: Catalog
    known_gaps: frozenset[Gap] = frozenset()

    @cached_property
    def market(self) -> Market:
        return Market(self.spec, self.catalog, self.known_gaps)


def on_grid(prices: pd.Series, grid: pd.DatetimeIndex) -> pd.Series:
    """The last price at or before each grid time."""
    last = prices.groupby(level=0, sort=True).last()
    last.index = pd.DatetimeIndex(last.index)
    return last.reindex(last.index.union(grid)).ffill().reindex(grid)


def _no_prices(
    instrument: InstrumentId, price_type: type, days: Sequence[object]
) -> MissingPricesError:
    return MissingPricesError(
        f"no {price_type.__name__} for {instrument} on "
        f"{', '.join(str(each) for each in days)}"
    )
