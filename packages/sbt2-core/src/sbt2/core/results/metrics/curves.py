from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd

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
    """A run's stored tables, measured in its settlement ``currency``."""

    equity: pd.DataFrame
    fills: pd.DataFrame
    carry: pd.DataFrame
    currency: str
    positions: pd.DataFrame = field(default_factory=pd.DataFrame)


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
