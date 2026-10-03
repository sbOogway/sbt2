import math
from collections.abc import Mapping
from dataclasses import dataclass
from statistics import NormalDist

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

from sbt2.core.results.metrics.analyzers import (
    finite,
    finite_values,
    nanos,
    portfolio_analyzer,
)
from sbt2.core.results.metrics.curves import (
    RunTables,
    Segment,
    compounded_daily,
    curve_returns,
    equity_curve,
)
from sbt2.core.results.metrics.trades import closed_trades


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


def full_metrics(
    run: RunTables, segment: Segment, curve: pd.Series | None = None
) -> FullMetrics:
    """Nautilus's full statistic set over the segment, annualized by its calendar.

    Return statistics come from mark-to-market equity on the segment's grid,
    ``curve`` when it is already built, trade statistics from the closed
    positions and position snapshots.
    """
    if curve is None:
        curve = equity_curve(run.equity, run.currency, segment)
    trades = closed_trades(run.positions, run.currency)
    returns = curve_returns(curve)
    return FullMetrics(
        pnls=_trade_statistics(trades, run.currency),
        returns=_return_statistics(returns, segment.days_per_year),
        general=_general_statistics(trades),
        pnls_by_instrument=_trade_statistics_by_instrument(trades, run.currency),
        probabilistic_sharpe=_probabilistic_sharpe(returns),
    )


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
    for ts, value in nanos(compounded_daily(returns)).items():
        analyzer.add_return(ts, value)
    statistics = analyzer.get_performance_stats_returns_vs_benchmark(
        nanos(compounded_daily(benchmark))
    )
    return finite_values(statistics)


def _relative_analyzer(days_per_year: int) -> PortfolioAnalyzer:
    return portfolio_analyzer(
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
    for ts, value in nanos(returns).items():
        analyzer.add_return(ts, value)
    return finite_values(analyzer.get_performance_stats_returns())


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
        for name, value in finite_values(statistics).items()
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
    return finite(pnls[pnls > 0].sum() / losses) if losses else None


def _general_statistics(trades: pd.DataFrame) -> dict[str, float | None]:
    """Nautilus's ``LongRatio``, rounded as it rounds.

    Its formula takes nautilus ``Position`` objects, which a stored run no
    longer has; the positions report keeps each one's entry side.
    """
    if trades.empty:
        return {}
    return {"Long Ratio": round(float((trades["entry"] == "BUY").mean()), 2)}


def _return_analyzer(days_per_year: int) -> PortfolioAnalyzer:
    return portfolio_analyzer(
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
    return portfolio_analyzer(
        AvgLoser(),
        AvgWinner(),
        Expectancy(),
        MaxLoser(),
        MaxWinner(),
        MinLoser(),
        MinWinner(),
        WinRate(),
    )
