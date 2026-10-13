from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import pandas as pd
from nautilus_trader.analysis import CAGR, MaxDrawdown, SharpeRatio

from sbt2.core.results.metrics.analyzers import finite, nanos
from sbt2.core.results.metrics.curves import (
    RunTables,
    Segment,
    curve_returns,
    equity_curve,
)
from sbt2.core.results.metrics.money import split_amounts, total


@dataclass(frozen=True)
class HeadlineMetrics:
    net_return: float | None
    annualized_return: float | None
    sharpe: float | None
    max_drawdown: float | None
    trade_count: int
    total_fees: float
    total_carry: float


def headline_metrics(run: RunTables, segment: Segment) -> HeadlineMetrics:
    """Headline metrics from mark-to-market equity over the segment."""
    curve = equity_curve(run.equity, run.currency, segment)
    returns = curve_returns(curve)
    period = segment.days_per_year
    return HeadlineMetrics(
        net_return=finite(curve.iloc[-1] / curve.iloc[0] - 1),
        annualized_return=_statistic(CAGR(period=period), returns),
        sharpe=_statistic(SharpeRatio(period=period), returns),
        max_drawdown=_statistic(MaxDrawdown(), returns),
        trade_count=len(run.fills),
        total_fees=_total_fees(run),
        total_carry=total(run.carry, "pnl_change", run.currency),
    )


def _total_fees(run: RunTables) -> float:
    """The commissions in the reporting currency, each converted at its fill."""
    if run.rates is None or run.fills.empty:
        return total(run.fills, "commission", run.currency)
    fees, currencies = split_amounts(run.fills["commission"])
    times = pd.DatetimeIndex(pd.to_datetime(run.fills["ts_event"], utc=True))
    factors = run.factors(currencies, times)
    return sum((fee * factor for fee, factor in zip(fees, factors, strict=True)), 0.0)


class _ReturnsStatistic(Protocol):
    def calculate_from_returns(
        self, raw_returns: Mapping[int, float]
    ) -> float | None: ...


def _statistic(statistic: _ReturnsStatistic, returns: pd.Series) -> float | None:
    return finite(statistic.calculate_from_returns(nanos(returns)))
