from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd
from nautilus_trader.model import InstrumentId

from sbt2.data import Catalog, Selection, Window
from sbt2.results.metrics import Segment
from sbt2.spec import ResolvedRunSpec


class BenchmarkCoverageError(LookupError):
    pass


@dataclass(frozen=True)
class _Market:
    run: ResolvedRunSpec
    catalog: Catalog
    grid: pd.DatetimeIndex

    @property
    def window(self) -> Window:
        return Window(self.run.start, self.run.end)


class Benchmark(ABC):
    """What a run is compared against, as returns on the run's equity grid."""

    def returns(self, run: ResolvedRunSpec, catalog: Catalog) -> pd.Series:
        """One return per step of the run's grid, indexed by its end."""
        market = _Market(run, catalog, Segment.of_run(run).grid)
        return self._value(market).pct_change().iloc[1:]

    @abstractmethod
    def _value(self, market: _Market) -> pd.Series:
        """The benchmark's value on the grid, 1 at the start before entry."""


@dataclass(frozen=True)
class BuyAndHold(Benchmark):
    """One instrument, the run's first when none is named, held by the
    asset class's buy-and-hold convention."""

    instrument: InstrumentId | None = None

    def _value(self, market: _Market) -> pd.Series:
        held = self.instrument or market.run.strategy.instruments[0]
        return _held([held], market)


@dataclass(frozen=True)
class EqualWeight(Benchmark):
    """The run's instruments, equal notional in each at the start, held without
    rebalancing, so the weights drift with the prices."""

    def _value(self, market: _Market) -> pd.Series:
        return _held(market.run.strategy.instruments, market)


def _held(instruments: Sequence[InstrumentId], market: _Market) -> pd.Series:
    """Equal notional in each instrument, bought at the start and held.

    Entry is at each instrument's first valuation price of the part.
    """
    convention = market.run.asset.buy_and_hold
    kept = 1 - float(convention.entry_fee(market.run.venue))
    relatives = [_prices(each, market) for each in instruments]
    basket = pd.concat([each / each.iloc[0] for each in relatives], axis=1)
    value = kept * basket.mean(axis=1)
    value.iloc[0] = 1.0
    return value


def _prices(instrument: InstrumentId, market: _Market) -> pd.Series:
    price_type = market.run.asset.buy_and_hold.price
    _check_coverage(instrument, price_type, market)
    frame = market.catalog.frame(instrument, price_type, market.window)
    if frame.empty:
        raise _no_prices(instrument, price_type, market.window.days)
    return _on_grid(pd.Series(frame["price"]), market.grid).bfill()


def _check_coverage(
    instrument: InstrumentId, price_type: type, market: _Market
) -> None:
    selection = Selection((instrument,), (price_type,), market.window)
    [coverage] = market.catalog.coverage(selection)
    if coverage.missing:
        raise _no_prices(instrument, price_type, coverage.missing)


def _no_prices(
    instrument: InstrumentId, price_type: type, days: Sequence[object]
) -> BenchmarkCoverageError:
    return BenchmarkCoverageError(
        f"no {price_type.__name__} for {instrument} on "
        f"{', '.join(str(each) for each in days)} to price the benchmark"
    )


def _on_grid(prices: pd.Series, grid: pd.DatetimeIndex) -> pd.Series:
    """The last price at or before each grid time."""
    last = prices.groupby(level=0, sort=True).last()
    last.index = pd.DatetimeIndex(last.index)
    return last.reindex(last.index.union(grid)).ffill().reindex(grid)
