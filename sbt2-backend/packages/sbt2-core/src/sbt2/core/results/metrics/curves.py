from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from sbt2.core.market import Rates
from sbt2.core.results.metrics.money import mismatch, split_amounts, total
from sbt2.core.spec import ResolvedRunSpec


@dataclass(frozen=True)
class Segment:
    """The dates metrics are computed over, and how equity is sampled on them."""

    start: datetime
    end: datetime
    interval: timedelta
    days_per_year: int

    @classmethod
    def of_run(cls, run: ResolvedRunSpec) -> Segment:
        return cls(
            run.start,
            run.end,
            timedelta(milliseconds=run.equity_interval_ms),
            run.asset.days_per_year,
        )

    @property
    def grid(self) -> pd.DatetimeIndex:
        """From the start at the equity interval, ending on the end."""
        grid = pd.date_range(self.start, self.end, freq=self.interval)
        return pd.DatetimeIndex(grid.union(pd.DatetimeIndex([self.end])))


@dataclass(frozen=True)
class RunTables:
    """A run's stored tables, measured in its reporting ``currency``.

    ``rates`` convert the amounts a run holds in other currencies; a run in one
    currency has none."""

    equity: pd.DataFrame
    fills: pd.DataFrame
    carry: pd.DataFrame
    currency: str
    positions: pd.DataFrame = field(default_factory=pd.DataFrame)
    orders: pd.DataFrame = field(default_factory=pd.DataFrame)
    margin: pd.DataFrame = field(default_factory=pd.DataFrame)
    trades: pd.DataFrame = field(default_factory=pd.DataFrame)
    rates: Rates | None = None

    def total(self, frame: pd.DataFrame, column: str) -> float:
        """The sum of a column of money amounts in the reporting currency, each
        converted at its ``ts_event``; 0 for an empty table."""
        if self.rates is None or frame.empty:
            return total(frame, column, self.currency)
        found, currencies = split_amounts(frame[column])
        times = pd.DatetimeIndex(pd.to_datetime(frame["ts_event"], utc=True))
        converted = np.asarray(found) * self.factors(currencies, times)
        return float(sum(converted.tolist(), 0.0))

    def factors(self, currencies: Sequence[str], times: pd.DatetimeIndex) -> np.ndarray:
        """By what to multiply an amount in each of ``currencies`` at the matching
        time to have it in the reporting currency; ``CurrencyMismatchError`` for
        another currency when the run has no rates."""
        if self.rates is not None:
            return self.rates.factors(currencies, times)
        foreign = set(currencies) - {self.currency}
        if foreign:
            raise mismatch(foreign, self.currency)
        return np.ones(len(times))


def equity_curve(equity: pd.DataFrame, currency: str, segment: Segment) -> pd.Series:
    """Equity in ``currency`` forward-filled onto the segment's grid.

    The grid runs from the segment start at the equity interval and ends on the
    segment end; warm-up snapshots only set the starting value.
    """
    rows = equity.loc[equity["currency"] == currency]
    last = rows.groupby("ts_event", sort=True)["total_equity"].last()
    series = pd.Series(last.to_numpy(), index=pd.DatetimeIndex(last.index))
    grid = segment.grid
    return series.reindex(series.index.union(grid)).ffill().reindex(grid)


def daily_returns(curve: pd.Series) -> pd.Series:
    """The returns of an equity curve, compounded to one per UTC day."""
    return compounded_daily(curve_returns(curve))


def curve_returns(curve: pd.Series) -> pd.Series:
    return curve.pct_change().iloc[1:]


def compounded_daily(returns: pd.Series) -> pd.Series:
    """Returns compounded to one per UTC day, labelled by the day's start.

    A return covers the step up to its time, so one at midnight belongs to
    the day before.
    """
    ends = pd.Series(returns.index, index=returns.index).dt.tz_convert("UTC")
    days = ends.dt.ceil("D") - pd.Timedelta(days=1)
    return (1 + returns).groupby(days).prod() - 1
