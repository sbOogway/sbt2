import math
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from nautilus_trader.analysis import CAGR, SharpeRatio

from sbt2.results import RunTables, Segment, full_metrics

START = datetime(2024, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)
YEAR = Segment(START, START + 365 * DAY, DAY, days_per_year=365)
NO_TABLE = pd.DataFrame()


def equity(points: dict[datetime, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_event": list(points),
            "currency": "USDT",
            "total_equity": list(points.values()),
        }
    )


def daily_equity(*values: float) -> pd.DataFrame:
    return equity({START + k * DAY: value for k, value in enumerate(values)})


def run_on(run_equity: pd.DataFrame) -> RunTables:
    return RunTables(run_equity, NO_TABLE, NO_TABLE, "USDT")


def wavy(days: int) -> list[float]:
    return [100.0 + 5 * math.sin(k) + k / 10 for k in range(days + 1)]


def nanos(values: list[float]) -> dict[int, float]:
    returns = pd.Series(values).pct_change().iloc[1:]
    return {
        int(pd.Timestamp(START + k * DAY).value): value
        for k, value in enumerate(returns, start=1)
    }


@pytest.mark.unit
def test_return_statistics_are_annualized_by_the_asset_calendar() -> None:
    values = wavy(365)

    returns = full_metrics(run_on(daily_equity(*values)), YEAR).returns

    assert returns["Sharpe Ratio (365 days)"] == pytest.approx(
        SharpeRatio(period=365).calculate_from_returns(nanos(values))
    )
    assert returns["CAGR (365 days)"] == pytest.approx(
        CAGR(period=365).calculate_from_returns(nanos(values))
    )
    assert returns["Sharpe Ratio (365 days)"] != pytest.approx(
        SharpeRatio(period=252).calculate_from_returns(nanos(values))
    )
    assert returns["CAGR (365 days)"] != pytest.approx(
        CAGR(period=252).calculate_from_returns(nanos(values))
    )
    assert not [name for name in returns if "252" in name]


@pytest.mark.unit
def test_return_statistics_cover_the_part_only() -> None:
    values = wavy(365)
    warmup = {START - k * DAY: 100.0 * (1 + (-1) ** k / 2) for k in range(10, 0, -1)}
    segment_only = daily_equity(*values)

    with_warmup = pd.concat([equity(warmup), segment_only])

    assert full_metrics(run_on(with_warmup), YEAR).returns == pytest.approx(
        full_metrics(run_on(segment_only), YEAR).returns
    )
