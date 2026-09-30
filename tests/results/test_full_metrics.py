import math
from datetime import UTC, datetime, timedelta
from statistics import NormalDist

import pandas as pd
import pytest
from nautilus_trader.analysis import CAGR, SharpeRatio

from sbt2.results import CurrencyMismatchError, RunTables, Segment, full_metrics
from sbt2.results.metrics import compounded_daily

START = datetime(2024, 1, 1, tzinfo=UTC)
DAY = timedelta(days=1)
YEAR = Segment(START, START + 365 * DAY, DAY, days_per_year=365)
NO_TABLE = pd.DataFrame()
BTC, ETH = "BTCUSDT-LINEAR.BYBIT", "ETHUSDT-LINEAR.BYBIT"


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


def closed(pnl: str, instrument: str = BTC, entry: str = "BUY") -> dict[str, object]:
    return {
        "instrument_id": instrument,
        "entry": entry,
        "realized_pnl": pnl,
        "ts_closed": pd.Timestamp(START + DAY),
        "is_snapshot": False,
    }


def snapshot(pnl: str) -> dict[str, object]:
    return {**closed(pnl), "is_snapshot": True}


def still_open(pnl: str) -> dict[str, object]:
    return {**closed(pnl), "ts_closed": pd.NA}


def with_positions(*rows: dict[str, object]) -> RunTables:
    positions = pd.DataFrame(
        list(rows), index=pd.Index([f"P-{k}" for k in range(len(rows))])
    )
    return RunTables(daily_equity(*wavy(365)), NO_TABLE, NO_TABLE, "USDT", positions)


def wavy(days: int) -> list[float]:
    return [100.0 + 5 * math.sin(k) + k / 10 for k in range(days + 1)]


def compounded(returns: list[float]) -> pd.DataFrame:
    values = [100.0]
    for each in returns:
        values.append(values[-1] * (1 + each))
    return daily_equity(*values)


def segment_of(days: int) -> Segment:
    return Segment(START, START + days * DAY, DAY, days_per_year=365)


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


@pytest.mark.unit
def test_trade_statistics_come_from_closed_positions() -> None:
    run = with_positions(
        closed("10 USDT"), closed("-5 USDT"), closed("20 USDT"), still_open("99 USDT")
    )

    pnls = full_metrics(run, YEAR).pnls

    assert pnls["Win Rate"] == pytest.approx(2 / 3)
    assert pnls["Profit Factor"] == pytest.approx(6.0)
    assert pnls["Expectancy"] == pytest.approx(2 / 3 * 15 - 1 / 3 * 5)
    assert pnls["Avg Winner"] == pytest.approx(15.0)
    assert pnls["Avg Loser"] == pytest.approx(-5.0)
    assert pnls["Max Winner"] == pytest.approx(20.0)


@pytest.mark.unit
def test_position_snapshots_count_as_trades() -> None:
    run = with_positions(closed("10 USDT"), snapshot("-5 USDT"))

    assert full_metrics(run, YEAR).pnls["Win Rate"] == pytest.approx(0.5)


@pytest.mark.unit
def test_long_ratio_is_the_share_of_trades_entered_long() -> None:
    run = with_positions(
        closed("10 USDT"),
        closed("-5 USDT", entry="SELL"),
        closed("20 USDT"),
        still_open("1 USDT"),
    )

    assert full_metrics(run, YEAR).general == {"Long Ratio": 0.67}


@pytest.mark.unit
def test_a_run_without_positions_has_no_trade_statistics() -> None:
    run = RunTables(daily_equity(*wavy(365)), NO_TABLE, NO_TABLE, "USDT", NO_TABLE)

    result = full_metrics(run, YEAR)

    assert result.pnls == {}
    assert result.general == {}
    assert result.returns["Sharpe Ratio (365 days)"] is not None


@pytest.mark.unit
def test_realized_pnl_in_another_currency_fails() -> None:
    run = with_positions(closed("10 USDT"), closed("-5 USDC"))

    with pytest.raises(CurrencyMismatchError, match="USDC"):
        full_metrics(run, YEAR)


@pytest.mark.unit
def test_trade_statistics_are_split_per_instrument() -> None:
    run = with_positions(
        closed("10 USDT", BTC), closed("-5 USDT", ETH), closed("20 USDT", BTC)
    )

    by_instrument = full_metrics(run, YEAR).pnls_by_instrument

    assert set(by_instrument) == {BTC, ETH}
    assert by_instrument[BTC]["Win Rate"] == pytest.approx(1.0)
    assert by_instrument[BTC]["Avg Winner"] == pytest.approx(15.0)
    assert by_instrument[ETH]["Win Rate"] == pytest.approx(0.0)
    assert by_instrument[ETH]["Avg Loser"] == pytest.approx(-5.0)


@pytest.mark.unit
def test_probabilistic_sharpe_ratio_follows_bailey_and_lopez_de_prado() -> None:
    returns = [0.01, -0.004, 0.012, 0.003, -0.02, 0.08, 0.005, -0.001, 0.002, 0.004]
    returns *= 3
    series = pd.Series(returns)
    sharpe = series.mean() / series.std()
    skew, kurtosis = series.skew(), series.kurt() + 3
    variance = 1 - skew * sharpe + (kurtosis - 1) / 4 * sharpe**2
    expected = NormalDist().cdf(sharpe * math.sqrt((len(returns) - 1) / variance))

    result = full_metrics(run_on(compounded(returns)), segment_of(len(returns)))

    assert skew > 1 and kurtosis > 3
    assert result.probabilistic_sharpe == pytest.approx(expected)


@pytest.mark.unit
def test_probabilistic_sharpe_is_one_half_when_the_sharpe_is_the_threshold() -> None:
    returns = [0.01, -0.01, 0.03, -0.03, 0.02, -0.02] * 5

    result = full_metrics(run_on(compounded(returns)), segment_of(len(returns)))

    assert result.probabilistic_sharpe == pytest.approx(0.5)


@pytest.mark.unit
def test_flat_equity_has_no_probabilistic_sharpe() -> None:
    result = full_metrics(run_on(daily_equity(100.0)), YEAR)

    assert result.probabilistic_sharpe is None


@pytest.mark.unit
def test_a_step_ending_at_midnight_belongs_to_the_day_before() -> None:
    hour = timedelta(hours=1)
    ends = pd.DatetimeIndex([START + k * hour for k in range(1, 49)])
    returns = pd.Series([0.001 * (k % 7 - 3) for k in range(48)], index=ends)

    daily = compounded_daily(returns)

    assert list(daily.index) == [pd.Timestamp(START), pd.Timestamp(START + DAY)]
    assert daily.iloc[0] == pytest.approx(
        math.prod(1 + each for each in returns.iloc[:24]) - 1
    )
    assert daily.iloc[1] == pytest.approx(
        math.prod(1 + each for each in returns.iloc[24:]) - 1
    )
