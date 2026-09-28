from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from sbt2.results import (
    CurrencyMismatchError,
    RunTables,
    Segment,
    equity_curve,
    headline_metrics,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)
SEGMENT = Segment(START, START + 4 * DAY, DAY, days_per_year=365)
NO_FILLS = pd.DataFrame()
NO_CARRY = pd.DataFrame()


def equity(points: dict[datetime, float], currency: str = "USDT") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_event": list(points),
            "currency": currency,
            "total_equity": list(points.values()),
        }
    )


def fills(*commissions: str) -> pd.DataFrame:
    return pd.DataFrame({"commission": list(commissions)})


def carry(*changes: str) -> pd.DataFrame:
    return pd.DataFrame({"pnl_change": list(changes)})


def daily_equity(*values: float) -> pd.DataFrame:
    return equity({START + k * DAY: value for k, value in enumerate(values)})


def metrics(
    run_equity: pd.DataFrame,
    segment: Segment = SEGMENT,
    benchmark: pd.Series | None = None,
):
    return headline_metrics(
        RunTables(run_equity, NO_FILLS, NO_CARRY, "USDT"), segment, benchmark
    )


@pytest.mark.unit
def test_equity_curve_is_forward_filled_from_warmup_onto_the_grid() -> None:
    snapshots = equity(
        {START - 2 * HOUR: 100.0, START + 30 * HOUR: 110.0, START + 4 * DAY: 120.0}
    )

    curve = equity_curve(snapshots, "USDT", SEGMENT)

    assert list(curve.index) == [START + k * DAY for k in range(5)]
    assert list(curve) == [100.0, 100.0, 110.0, 110.0, 120.0]


@pytest.mark.unit
def test_equity_curve_keeps_the_last_snapshot_at_a_timestamp_and_one_currency() -> None:
    snapshots = pd.concat(
        [
            equity({START: 100.0}),
            equity({START: 101.0}),
            equity({START: 5.0}, currency="BTC"),
        ]
    )

    assert equity_curve(snapshots, "USDT", SEGMENT).iloc[0] == 101.0


@pytest.mark.unit
def test_equity_curve_ends_on_the_segment_end_off_the_interval() -> None:
    segment = Segment(START, START + DAY + HOUR, DAY, days_per_year=365)

    curve = equity_curve(daily_equity(100.0), "USDT", segment)

    assert list(curve.index) == [START, START + DAY, START + DAY + HOUR]


@pytest.mark.unit
def test_net_return_and_max_drawdown_come_from_the_curve() -> None:
    result = metrics(daily_equity(100.0, 120.0, 90.0, 99.0, 110.0))

    assert result.net_return == pytest.approx(0.10)
    assert result.max_drawdown == pytest.approx(-0.25)


@pytest.mark.unit
def test_annualized_statistics_use_the_asset_calendar_year() -> None:
    run_equity = daily_equity(100.0, 101.0, 100.5, 102.0, 103.0)
    stock_year = Segment(START, START + 4 * DAY, DAY, days_per_year=252)

    crypto, stock = metrics(run_equity), metrics(run_equity, stock_year)

    assert crypto.sharpe is not None and stock.sharpe is not None
    assert crypto.sharpe / stock.sharpe == pytest.approx((365 / 252) ** 0.5)
    assert crypto.annualized_return != stock.annualized_return


@pytest.mark.unit
def test_flat_equity_has_no_sharpe() -> None:
    assert metrics(daily_equity(100.0)).sharpe is None


@pytest.mark.unit
def test_alpha_and_beta_are_absent_without_a_benchmark() -> None:
    result = metrics(daily_equity(100.0, 101.0, 100.5, 102.0, 103.0))

    assert (result.alpha, result.beta) == (None, None)


@pytest.mark.unit
def test_alpha_and_beta_against_intraday_benchmark_returns() -> None:
    run_equity = daily_equity(100.0, 101.0, 100.5, 102.0, 103.0)
    curve = equity_curve(run_equity, "USDT", SEGMENT)
    own_daily = curve.pct_change().iloc[1:]
    benchmark = pd.Series(
        [(1 + r) ** 0.5 - 1 for r in own_daily for _ in range(2)],
        index=[day + half for day in own_daily.index for half in (0 * HOUR, 12 * HOUR)],
    )

    result = metrics(run_equity, benchmark=benchmark)

    assert result.beta == pytest.approx(1.0)
    assert result.alpha == pytest.approx(0.0, abs=1e-9)


@pytest.mark.unit
def test_trades_fees_and_carry_are_totalled_in_the_settlement_currency() -> None:
    run = RunTables(
        daily_equity(100.0),
        fills("0.50 USDT", "0.25 USDT"),
        carry("-5.00 USDT", "1.50 USDT"),
        "USDT",
    )

    result = headline_metrics(run, SEGMENT)

    assert result.trade_count == 2
    assert result.total_fees == pytest.approx(0.75)
    assert result.total_carry == pytest.approx(-3.5)


@pytest.mark.unit
def test_a_run_without_fills_or_carry_totals_zero() -> None:
    result = metrics(daily_equity(100.0))

    assert (result.trade_count, result.total_fees, result.total_carry) == (0, 0, 0)


@pytest.mark.unit
def test_amounts_in_another_currency_fail() -> None:
    run = RunTables(daily_equity(100.0), fills("0.001 BTC"), NO_CARRY, "USDT")

    with pytest.raises(CurrencyMismatchError, match="BTC"):
        headline_metrics(run, SEGMENT)
