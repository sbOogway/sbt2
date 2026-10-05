import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from price_catalog import BTC, PriceCatalog, run_on

from sbt2.core.results import (
    BuyAndHold,
    PricedRun,
    RunTables,
    tearsheet_panels,
)
from sbt2.core.results.metrics import compounded_daily, daily_returns

DAY = timedelta(days=1)


@pytest.fixture
def prices(tmp_path: Path) -> PriceCatalog:
    return PriceCatalog(tmp_path)


def daily_run(prices: PriceCatalog, start: datetime, values: list[float]) -> PricedRun:
    """A run with one equity point per day from ``start``."""
    days = len(values) - 1
    spec = replace(
        run_on([BTC], start, start + days * DAY), equity_interval_ms=86_400_000
    )
    equity = pd.DataFrame(
        {
            "ts_event": [start + k * DAY for k in range(len(values))],
            "currency": "USDT",
            "total_equity": values,
        }
    )
    tables = RunTables(equity, pd.DataFrame(), pd.DataFrame(), "USDT")
    return PricedRun(spec, tables, prices.catalog)


def wavy(days: int) -> list[float]:
    return [10_000.0 + 50 * ((k * 7) % 5) + 3 * k for k in range(days + 1)]


@pytest.mark.unit
def test_the_panel_returns_are_the_tearsheets_daily_returns(
    prices: PriceCatalog,
) -> None:
    run = daily_run(prices, datetime(2024, 1, 1, tzinfo=UTC), wavy(10))

    panels = tearsheet_panels(run)

    pd.testing.assert_series_equal(panels.returns, daily_returns(run.equity))


@pytest.mark.unit
def test_the_drawdown_starts_at_zero_and_falls_below_the_running_peak(
    prices: PriceCatalog,
) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    run = daily_run(prices, start, [100.0, 110.0, 88.0, 92.4])

    drawdown = tearsheet_panels(run).drawdown

    assert list(drawdown.index) == [
        start - timedelta(seconds=1),
        start,
        start + DAY,
        start + 2 * DAY,
    ]
    assert list(drawdown) == pytest.approx([0.0, 0.0, -0.2, -0.16])


@pytest.mark.unit
def test_monthly_and_yearly_returns_compound_the_daily_returns(
    prices: PriceCatalog,
) -> None:
    run = daily_run(
        prices, datetime(2023, 12, 30, tzinfo=UTC), [100.0, 110.0, 99.0, 104.94]
    )

    panels = tearsheet_panels(run)

    assert list(panels.monthly_returns.index) == [
        pd.Timestamp("2023-12-31", tz="UTC"),
        pd.Timestamp("2024-01-31", tz="UTC"),
    ]
    assert list(panels.monthly_returns) == pytest.approx([1.1 * 0.9 - 1, 0.06])
    assert list(panels.yearly_returns.index) == [
        pd.Timestamp("2023-12-31", tz="UTC"),
        pd.Timestamp("2024-12-31", tz="UTC"),
    ]
    assert list(panels.yearly_returns) == pytest.approx([1.1 * 0.9 - 1, 0.06])


@pytest.mark.unit
def test_the_benchmark_returns_are_the_overlaid_benchmark(
    prices: PriceCatalog,
) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    run = daily_run(prices, start, wavy(3))
    prices.add_marks(BTC, {start + k * DAY: 50_000.0 + 700 * k**2 for k in range(4)})
    benchmark = BuyAndHold()

    panels = tearsheet_panels(run, benchmark)

    expected = compounded_daily(benchmark.returns(run))
    pd.testing.assert_series_equal(panels.benchmark_returns, expected)
    assert not panels.benchmark_returns.empty
    assert tearsheet_panels(run).benchmark_returns.empty


@pytest.mark.unit
def test_the_rolling_sharpe_is_annualized_by_the_asset_calendar(
    prices: PriceCatalog,
) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    values = wavy(80)
    returns = pd.Series(values).pct_change().iloc[1:]
    rolling = returns.rolling(60)
    expected = pd.Series(rolling.mean() / rolling.std()).dropna() * math.sqrt(365)

    sharpe = tearsheet_panels(daily_run(prices, start, values)).rolling_sharpe

    np.testing.assert_allclose(sharpe.to_numpy(), expected.to_numpy())
    assert tearsheet_panels(daily_run(prices, start, wavy(30))).rolling_sharpe.empty


@pytest.mark.unit
def test_the_rolling_sharpe_keeps_the_undefined_values_of_flat_windows(
    prices: PriceCatalog,
) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    varied = wavy(20)
    values = varied + [varied[-1]] * 70

    sharpe = tearsheet_panels(daily_run(prices, start, values)).rolling_sharpe

    assert len(sharpe) == 90 - 59
    assert sharpe.index[0] == start + 59 * DAY
    assert not math.isnan(sharpe.iloc[0])
    assert sharpe.iloc[:20].notna().all()
    assert sharpe.iloc[-11:].isna().all()
