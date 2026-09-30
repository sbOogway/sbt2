import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

import pandas as pd
from nautilus_trader.analysis import (
    CAGR,
    Alpha,
    AvgLoser,
    AvgWinner,
    BetaRatio,
    CalmarRatio,
    DownCaptureRatio,
    Expectancy,
    ExpectedShortfall,
    InformationRatio,
    LongRatio,
    MaxDrawdown,
    MaxLoser,
    MaxWinner,
    MinLoser,
    MinWinner,
    OmegaRatio,
    PortfolioAnalyzer,
    ProfitFactor,
    ReturnsAverage,
    ReturnsAverageLoss,
    ReturnsAverageWin,
    ReturnsKurtosis,
    ReturnsSkewness,
    ReturnsVolatility,
    RiskReturnRatio,
    SharpeRatio,
    SortinoRatio,
    TailRatio,
    TrackingError,
    UlcerIndex,
    UpCaptureRatio,
    ValueAtRisk,
    WinRate,
)
from nautilus_trader.model import Money

from sbt2.spec import ResolvedRunSpec


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


@dataclass(frozen=True)
class HeadlineMetrics:
    net_return: float | None
    annualized_return: float | None
    sharpe: float | None
    max_drawdown: float | None
    trade_count: int
    total_fees: float
    total_carry: float


@dataclass(frozen=True)
class FullMetrics:
    """Nautilus's statistics of a run, under its own names."""

    returns: dict[str, float | None]


class CurrencyMismatchError(ValueError):
    pass


def headline_metrics(run: RunTables, segment: Segment) -> HeadlineMetrics:
    """Headline metrics from mark-to-market equity over the segment."""
    curve = equity_curve(run.equity, run.currency, segment)
    returns = _returns(curve)
    period = segment.days_per_year
    return HeadlineMetrics(
        net_return=_finite(curve.iloc[-1] / curve.iloc[0] - 1),
        annualized_return=_statistic(CAGR(period=period), returns),
        sharpe=_statistic(SharpeRatio(period=period), returns),
        max_drawdown=_statistic(MaxDrawdown(), returns),
        trade_count=len(run.fills),
        total_fees=_total(run.fills, "commission", run.currency),
        total_carry=_total(run.carry, "pnl_change", run.currency),
    )


def full_metrics(run: RunTables, segment: Segment) -> FullMetrics:
    """Nautilus's full statistic set over the segment, annualized by its calendar.

    Return statistics come from mark-to-market equity on the segment's grid.
    """
    analyzer = _full_analyzer(segment.days_per_year)
    curve = equity_curve(run.equity, run.currency, segment)
    for ts, value in _nanos(_returns(curve)).items():
        analyzer.add_return(ts, value)
    return FullMetrics(returns=_finite_values(analyzer.get_performance_stats_returns()))


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


def benchmark_statistics(
    returns: pd.Series, benchmark: pd.Series | None, days_per_year: int
) -> dict[str, float | None]:
    """Nautilus's benchmark-relative statistics, under its own names.

    Both return series are compounded to daily returns first, since nautilus
    pairs them only on identical timestamps. Without a benchmark there are none.
    """
    if benchmark is None:
        return {}
    analyzer = _relative_analyzer(days_per_year)
    for ts, value in _nanos(_daily(returns)).items():
        analyzer.add_return(ts, value)
    statistics = analyzer.get_performance_stats_returns_vs_benchmark(
        _nanos(_daily(benchmark))
    )
    return _finite_values(statistics)


def _relative_analyzer(days_per_year: int) -> PortfolioAnalyzer:
    return _analyzer(
        Alpha(period=days_per_year),
        BetaRatio(),
        InformationRatio(period=days_per_year),
        TrackingError(period=days_per_year),
        UpCaptureRatio(period=days_per_year),
        DownCaptureRatio(period=days_per_year),
    )


def _full_analyzer(days_per_year: int) -> PortfolioAnalyzer:
    """Every nautilus statistic that needs no benchmark."""
    return _analyzer(
        CAGR(period=days_per_year),
        CalmarRatio(period=days_per_year),
        ReturnsVolatility(period=days_per_year),
        SharpeRatio(period=days_per_year),
        SortinoRatio(period=days_per_year),
        MaxDrawdown(),
        ExpectedShortfall(),
        ValueAtRisk(),
        OmegaRatio(),
        ProfitFactor(),
        ReturnsAverage(),
        ReturnsAverageLoss(),
        ReturnsAverageWin(),
        ReturnsKurtosis(),
        ReturnsSkewness(),
        RiskReturnRatio(),
        TailRatio(),
        UlcerIndex(),
        AvgLoser(),
        AvgWinner(),
        Expectancy(),
        LongRatio(),
        MaxLoser(),
        MaxWinner(),
        MinLoser(),
        MinWinner(),
        WinRate(),
    )


def _analyzer(*statistics: object) -> PortfolioAnalyzer:
    analyzer = PortfolioAnalyzer()
    for statistic in statistics:
        analyzer.register_statistic(statistic)
    return analyzer


class _ReturnsStatistic(Protocol):
    def calculate_from_returns(
        self, raw_returns: Mapping[int, float]
    ) -> float | None: ...


def _statistic(statistic: _ReturnsStatistic, returns: pd.Series) -> float | None:
    return _finite(statistic.calculate_from_returns(_nanos(returns)))


def _returns(curve: pd.Series) -> pd.Series:
    return curve.pct_change().iloc[1:]


def _daily(returns: pd.Series) -> pd.Series:
    days = pd.Series(returns.index, index=returns.index).dt.tz_convert("UTC")
    return (1 + returns).groupby(days.dt.floor("D")).prod() - 1


def _nanos(returns: pd.Series) -> dict[int, float]:
    index = pd.DatetimeIndex(returns.index)
    return {
        int(ts.value): float(value) for ts, value in zip(index, returns, strict=True)
    }


def _total(frame: pd.DataFrame, column: str, currency: str) -> float:
    if frame.empty:
        return 0.0
    amounts = [Money.from_str(each) for each in frame[column]]
    foreign = {each.currency.code for each in amounts} - {currency}
    if foreign:
        raise _mismatch(foreign, currency)
    return sum((each.as_double() for each in amounts), 0.0)


def _mismatch(foreign: set[str], currency: str) -> CurrencyMismatchError:
    return CurrencyMismatchError(
        f"amounts in {', '.join(sorted(foreign))}, not the settlement currency {currency}"
    )


def _finite_values(statistics: Mapping[str, float]) -> dict[str, float | None]:
    return {name: _finite(value) for name, value in statistics.items()}


def _finite(value: float | None) -> float | None:
    return float(value) if value is not None and math.isfinite(value) else None
