"""The series behind a tearsheet's panels, as fractions indexed by UTC time."""

import math
from dataclasses import dataclass

import pandas as pd

ROLLING_WINDOW = 60


@dataclass(frozen=True)
class TearsheetPanels:
    """The series a tearsheet draws, for the run and, when overlaid, its
    benchmark. All values are fractions; the benchmark's returns are empty
    without a benchmark and the rolling Sharpe is empty on a run shorter than
    its window."""

    returns: pd.Series
    benchmark_returns: pd.Series
    drawdown: pd.Series
    monthly_returns: pd.Series
    yearly_returns: pd.Series
    rolling_sharpe: pd.Series


def drawdown(returns: pd.Series) -> pd.Series:
    """Equity compounded from 1 one second before the first return, below its
    running peak as a fraction of it; the baseline row is included."""
    if returns.empty:
        return empty_series()
    baseline = pd.DatetimeIndex(returns.index)[0] - pd.Timedelta(seconds=1)
    equity = pd.concat(
        [pd.Series([1.0], index=pd.DatetimeIndex([baseline])), 1 + returns]
    ).cumprod()
    peak = equity.cummax()
    return (equity - peak) / peak


def monthly_returns(returns: pd.Series) -> pd.Series:
    """Returns compounded per calendar month, labelled by the month's last day."""
    return _compounded(returns, "ME")


def yearly_returns(returns: pd.Series) -> pd.Series:
    """Returns compounded per calendar year, labelled by the year's last day."""
    return _compounded(returns, "YE")


def rolling_sharpe(returns: pd.Series, days_per_year: int) -> pd.Series:
    """The Sharpe ratio over the last 60 returns, annualized by ``days_per_year``."""
    if len(returns) < ROLLING_WINDOW:
        return empty_series()
    rolling = returns.rolling(ROLLING_WINDOW)
    volatility = pd.Series(rolling.std()).replace(0, math.nan)
    sharpe = pd.Series(rolling.mean() / volatility) * math.sqrt(days_per_year)
    return sharpe.dropna()


def _compounded(returns: pd.Series, period: str) -> pd.Series:
    if returns.empty:
        return empty_series()
    return (1 + returns).resample(period).prod() - 1


def empty_series() -> pd.Series:
    return pd.Series([], index=pd.DatetimeIndex([], tz="UTC"), dtype="float64")
