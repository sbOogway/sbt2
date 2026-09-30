import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import NormalDist
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
from nautilus_trader.model import Currency, Money, PositionId

from sbt2.results.money import total
from sbt2.results.trades import closed_trades
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
    positions: pd.DataFrame = field(default_factory=pd.DataFrame)


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
    """Nautilus's pnls, returns and general statistics of a run under its own
    names, the pnls again per instrument id, and the probabilistic Sharpe ratio."""

    pnls: dict[str, float | None]
    returns: dict[str, float | None]
    general: dict[str, float | None]
    pnls_by_instrument: dict[str, dict[str, float | None]]
    probabilistic_sharpe: float | None


_ACCOUNT_STATISTICS = ("PnL (total)", "PnL% (total)")
"""Nautilus computes these from the account's balances, which trades alone lack."""


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
        total_fees=total(run.fills, "commission", run.currency),
        total_carry=total(run.carry, "pnl_change", run.currency),
    )


def full_metrics(run: RunTables, segment: Segment) -> FullMetrics:
    """Nautilus's full statistic set over the segment, annualized by its calendar.

    Return statistics come from mark-to-market equity on the segment's grid,
    trade statistics from the closed positions and position snapshots.
    """
    trades = closed_trades(run.positions, run.currency)
    returns = _returns(equity_curve(run.equity, run.currency, segment))
    return FullMetrics(
        pnls=_trade_statistics(trades, run.currency),
        returns=_return_statistics(returns, segment.days_per_year),
        general=_general_statistics(trades),
        pnls_by_instrument=_trade_statistics_by_instrument(trades, run.currency),
        probabilistic_sharpe=_probabilistic_sharpe(returns),
    )


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


def daily_returns(run: RunTables, segment: Segment) -> pd.Series:
    """The returns of the run's equity on the segment's grid, compounded to
    one per UTC day."""
    return _daily(_returns(equity_curve(run.equity, run.currency, segment)))


def _relative_analyzer(days_per_year: int) -> PortfolioAnalyzer:
    return _analyzer(
        Alpha(period=days_per_year),
        BetaRatio(),
        InformationRatio(period=days_per_year),
        TrackingError(period=days_per_year),
        UpCaptureRatio(period=days_per_year),
        DownCaptureRatio(period=days_per_year),
    )


def _return_statistics(
    returns: pd.Series, days_per_year: int
) -> dict[str, float | None]:
    analyzer = _return_analyzer(days_per_year)
    for ts, value in _nanos(returns).items():
        analyzer.add_return(ts, value)
    return _finite_values(analyzer.get_performance_stats_returns())


def _probabilistic_sharpe(returns: pd.Series) -> float | None:
    """The probability that the true Sharpe ratio is above 0.

    Bailey & López de Prado (2012), https://papers.ssrn.com/abstract=1821643,
    on the grid's returns, not annualized. The skewness and excess kurtosis
    are the unbiased sample estimators of nautilus's ``ReturnsSkewness`` and
    ``ReturnsKurtosis``, which resample to daily returns first and so can't
    take the grid's own.
    """
    volatility = returns.std()
    if not volatility > 0:
        return None
    sharpe = returns.mean() / volatility
    kurtosis = returns.kurt() + 3
    variance = 1 - returns.skew() * sharpe + (kurtosis - 1) / 4 * sharpe**2
    if not variance > 0:
        return None
    return NormalDist().cdf(sharpe * math.sqrt((len(returns) - 1) / variance))


def _trade_statistics(trades: pd.DataFrame, currency: str) -> dict[str, float | None]:
    if trades.empty:
        return {}
    settlement = Currency.from_str(currency)
    pnls = pd.Series(trades["pnl"], dtype=float)
    closed_at = pd.DatetimeIndex(trades["ts_closed"])
    analyzer = _trade_analyzer()
    for position_id, ts, pnl in zip(trades.index, closed_at, pnls, strict=True):
        analyzer.add_trade(
            PositionId(str(position_id)), ts.value, Money(pnl, settlement)
        )
    statistics = analyzer.get_performance_stats_pnls(settlement, None)
    return {**_without_account(statistics), "Profit Factor": _profit_factor(pnls)}


def _without_account(statistics: Mapping[str, float]) -> dict[str, float | None]:
    return {
        name: value
        for name, value in _finite_values(statistics).items()
        if name not in _ACCOUNT_STATISTICS
    }


def _trade_statistics_by_instrument(
    trades: pd.DataFrame, currency: str
) -> dict[str, dict[str, float | None]]:
    return {
        str(instrument): _trade_statistics(each, currency)
        for instrument, each in trades.groupby("instrument_id")
    }


def _profit_factor(pnls: pd.Series) -> float | None:
    """Nautilus's ``ProfitFactor`` takes returns only, not realized PnLs."""
    losses = -pnls[pnls < 0].sum()
    return _finite(pnls[pnls > 0].sum() / losses) if losses else None


def _general_statistics(trades: pd.DataFrame) -> dict[str, float | None]:
    """Nautilus's ``LongRatio``, rounded as it rounds.

    Its formula takes nautilus ``Position`` objects, which a stored run no
    longer has; the positions report keeps each one's entry side.
    """
    if trades.empty:
        return {}
    return {"Long Ratio": round(float((trades["entry"] == "BUY").mean()), 2)}


def _return_analyzer(days_per_year: int) -> PortfolioAnalyzer:
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
    )


def _trade_analyzer() -> PortfolioAnalyzer:
    return _analyzer(
        AvgLoser(),
        AvgWinner(),
        Expectancy(),
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


def _finite_values(statistics: Mapping[str, float]) -> dict[str, float | None]:
    return {name: _finite(value) for name, value in statistics.items()}


def _finite(value: float | None) -> float | None:
    return float(value) if value is not None and math.isfinite(value) else None
