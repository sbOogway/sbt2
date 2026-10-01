from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pandas as pd
from nautilus_trader.model import InstrumentId

from sbt2.results.pricing import Market, MissingPricesError, PricedRun, on_grid


class BenchmarkCoverageError(LookupError):
    pass


class UnknownBenchmarkError(LookupError):
    pass


class BenchmarkArgumentError(ValueError):
    pass


class Benchmark(ABC):
    """What a run is compared against, as returns on the run's equity grid."""

    def returns(self, run: PricedRun) -> pd.Series:
        """One return per step of the run's grid, indexed by its end.

        Prices are carried across the run's known gaps, the days it skipped.
        """
        return self._value(run.market).pct_change().iloc[1:]

    @abstractmethod
    def _value(self, market: Market) -> pd.Series:
        """The benchmark's value on the grid, 1 at the start before entry."""


@dataclass(frozen=True)
class BuyAndHold(Benchmark):
    """One instrument, the run's first when none is named, held by the
    asset class's buy-and-hold convention."""

    instrument: InstrumentId | None = None

    def _value(self, market: Market) -> pd.Series:
        held = self.instrument or market.run.strategy.instruments[0]
        return _held([held], market)


@dataclass(frozen=True)
class EqualWeight(Benchmark):
    """The run's instruments, equal notional in each at the start, held without
    rebalancing, so the weights drift with the prices."""

    def _value(self, market: Market) -> pd.Series:
        return _held(market.run.strategy.instruments, market)


@dataclass(frozen=True)
class External(Benchmark):
    """Prices from a CSV or parquet file with a UTC ``timestamp`` column and a
    ``price`` column, held without fees from the part start."""

    path: Path

    def _value(self, market: Market) -> pd.Series:
        prices = self._prices()
        self._check_covers(prices, market)
        held = on_grid(prices, market.grid)
        return held / held.iloc[0]

    def _check_covers(self, prices: pd.Series, market: Market) -> None:
        """A price at or before the start, and one within the last equity
        interval of the end, so a sparser file needn't tick on the end."""
        start = market.grid[0]
        if prices.empty or prices.index[0] > start:
            raise BenchmarkCoverageError(
                f"the benchmark file {self.path} has no price at {start}"
            )
        needed = market.grid[-1] - timedelta(milliseconds=market.run.equity_interval_ms)
        if prices.index[-1] < needed:
            raise BenchmarkCoverageError(
                f"the benchmark file {self.path} ends at {prices.index[-1]}, "
                f"before {needed}"
            )

    def _prices(self) -> pd.Series:
        frame = (
            pd.read_csv(self.path)
            if self.path.suffix == ".csv"
            else pd.read_parquet(self.path)
        )
        index = pd.DatetimeIndex(pd.to_datetime(frame["timestamp"], utc=True))
        return pd.Series(frame["price"].to_numpy(dtype=float), index=index).sort_index()


def _held(instruments: Sequence[InstrumentId], market: Market) -> pd.Series:
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


def _prices(instrument: InstrumentId, market: Market) -> pd.Series:
    try:
        return market.prices(instrument, market.run.asset.buy_and_hold.price)
    except MissingPricesError as error:
        raise BenchmarkCoverageError(f"{error} to price the benchmark") from None


def build_benchmark(name: str, argument: str | None = None) -> Benchmark | None:
    """The benchmark called ``name``; ``none`` is no benchmark.

    ``argument`` is the instrument id of ``buy-and-hold``, which defaults to the
    run's first instrument, or the file of ``external``.
    """
    try:
        builder = _BUILDERS[name]
    except KeyError:
        raise UnknownBenchmarkError(
            f"no benchmark {name}; known: {', '.join(sorted(_BUILDERS))}"
        ) from None
    return builder(name, argument)


def _buy_and_hold(_name: str, argument: str | None) -> Benchmark:
    return BuyAndHold(None if argument is None else InstrumentId.from_str(argument))


def _equal_weight(name: str, argument: str | None) -> Benchmark:
    _refuse(name, argument)
    return EqualWeight()


def _external(name: str, argument: str | None) -> Benchmark:
    if argument is None:
        raise BenchmarkArgumentError(f"the benchmark {name} needs a file")
    return External(Path(argument))


def _none(name: str, argument: str | None) -> None:
    _refuse(name, argument)


def _refuse(name: str, argument: str | None) -> None:
    if argument is not None:
        raise BenchmarkArgumentError(
            f"the benchmark {name} takes no argument, got {argument!r}"
        )


_BUILDERS: dict[str, Callable[[str, str | None], Benchmark | None]] = {
    "buy-and-hold": _buy_and_hold,
    "equal-weight": _equal_weight,
    "external": _external,
    "none": _none,
}
