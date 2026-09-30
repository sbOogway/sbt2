import math
from dataclasses import astuple, replace
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from nautilus_trader.model import InstrumentId
from plotted import Plotted, plotted
from price_catalog import BTC, ETH, PriceCatalog, run_on

from sbt2.results import (
    BuyAndHold,
    PricedRun,
    RunTables,
    costs_and_exposure,
    tearsheet,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


@pytest.fixture
def prices(tmp_path: Path) -> PriceCatalog:
    return PriceCatalog(tmp_path)


def equity(points: dict[datetime, float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_event": list(points),
            "currency": "USDT",
            "total_equity": list(points.values()),
        }
    )


def fill(instrument: InstrumentId, at: datetime, quantity: float, price: float):
    """A fill paying 1 USDT; a negative quantity sells."""
    return {
        "instrument_id": str(instrument),
        "order_side": "BUY" if quantity > 0 else "SELL",
        "last_qty": str(abs(quantity)),
        "last_px": str(price),
        "commission": "1 USDT",
        "ts_event": pd.Timestamp(at),
    }


def funding(instrument: InstrumentId, at: datetime, amount: float) -> dict[str, Any]:
    return {
        "instrument_id": str(instrument),
        "pnl_change": f"{amount} USDT",
        "ts_event": pd.Timestamp(at),
    }


def closed(instrument: InstrumentId, pnl: float, at: datetime) -> dict[str, Any]:
    return {
        "instrument_id": str(instrument),
        "entry": "BUY",
        "realized_pnl": f"{pnl} USDT",
        "ts_closed": pd.Timestamp(at),
        "duration_ns": int(HOUR.total_seconds() * 1e9),
    }


def hourly(values: list[float]) -> dict[datetime, float]:
    return {START + k * HOUR: value for k, value in enumerate(values)}


def wavy(hours: int) -> list[float]:
    return [10_000.0 + 50 * ((k * 7) % 5) + 3 * k for k in range(hours + 1)]


def btc_round_trip(prices: PriceCatalog) -> PricedRun:
    """1 BTC bought at 50000 and sold at 51000 within two days, paying funding."""
    end = START + 2 * DAY
    prices.add_marks(BTC, {START + k * HOUR: 50_000.0 + 20 * k for k in range(49)})
    tables = RunTables(
        equity(hourly(wavy(48))),
        pd.DataFrame(
            [fill(BTC, START + HOUR, 1, 50_000.0), fill(BTC, START + DAY, -1, 51_000.0)]
        ),
        pd.DataFrame([funding(BTC, START + 8 * HOUR, -5.0)]),
        "USDT",
        pd.DataFrame([closed(BTC, 998.0, START + DAY)], index=pd.Index(["P-1"])),
    )
    return PricedRun(run_on([BTC], START, end), tables, prices.catalog)


def btc_and_eth(prices: PriceCatalog) -> PricedRun:
    """The BTC round trip, and 10 ETH bought at 2500 and sold at 2600 at a loss
    of 3 USDT."""
    btc = btc_round_trip(prices)
    prices.add_marks(ETH, {START + k * HOUR: 2_500.0 + k for k in range(49)})
    eth_fills = [
        fill(ETH, START + 2 * HOUR, 10, 2_500.0),
        fill(ETH, START + 30 * HOUR, -10, 2_600.0),
    ]
    tables = replace(
        btc.tables,
        fills=pd.concat([btc.tables.fills, pd.DataFrame(eth_fills)]),
        positions=pd.concat(
            [
                btc.tables.positions,
                pd.DataFrame(
                    [closed(ETH, -3.0, START + 30 * HOUR)], index=pd.Index(["P-2"])
                ),
            ]
        ),
    )
    spec = run_on([BTC, ETH], START, START + 2 * DAY)
    return PricedRun(spec, tables, prices.catalog)


def drawn(run: PricedRun, path: Path, **options: Any) -> Plotted:
    target = path / "tearsheet.html"
    tearsheet(run, target, **options)
    return plotted(target.read_text())


def statistic_names(figure: Plotted) -> list[str]:
    [table] = [
        each
        for each in figure.of_type("table")
        if each["header"]["values"] == ["<b>Metric</b>", "<b>Value</b>"]
    ]
    return table["cells"]["values"][0]


def instrument_rows(figure: Plotted) -> dict[str, dict[str, str]]:
    [table] = [
        each
        for each in figure.of_type("table")
        if each["header"]["values"][0] == "<b>Instrument</b>"
    ]
    header = [
        each.removeprefix("<b>").removesuffix("</b>")
        for each in table["header"]["values"]
    ]
    rows = zip(*table["cells"]["values"], strict=True)
    return {row[0]: dict(zip(header[1:], row[1:], strict=True)) for row in rows}


@pytest.mark.unit
def test_the_tearsheet_is_written_to_the_given_path(
    prices: PriceCatalog, tmp_path: Path
) -> None:
    target = tmp_path / "report" / "tearsheet.html"
    target.parent.mkdir()

    tearsheet(btc_round_trip(prices), target)

    assert "Plotly.newPlot(" in target.read_text()


@pytest.mark.unit
def test_a_run_without_trades_still_gets_a_tearsheet(
    prices: PriceCatalog, tmp_path: Path
) -> None:
    run = PricedRun(
        run_on([BTC], START, START + 2 * DAY),
        RunTables(equity(hourly(wavy(48))), pd.DataFrame(), pd.DataFrame(), "USDT"),
        prices.catalog,
    )

    assert instrument_rows(drawn(run, tmp_path)) == {}


@pytest.mark.unit
def test_the_stats_table_shows_the_full_metrics_annualized_by_the_calendar(
    prices: PriceCatalog, tmp_path: Path
) -> None:
    names = statistic_names(drawn(btc_round_trip(prices), tmp_path))

    assert "Sharpe Ratio (365 days)" in names
    assert "Probabilistic Sharpe Ratio" in names
    assert "Win Rate" in names
    assert not [each for each in names if "252 days" in each]


@pytest.mark.unit
def test_the_tearsheet_is_built_from_daily_returns(
    prices: PriceCatalog, tmp_path: Path
) -> None:
    values = wavy(71)
    run = PricedRun(
        run_on([BTC], START, START + 71 * HOUR),
        RunTables(equity(hourly(values)), pd.DataFrame(), pd.DataFrame(), "USDT"),
        prices.catalog,
    )
    day_ends = [values[0], values[24], values[48], values[71]]
    daily = [after / before - 1 for before, after in pairwise(day_ends)]

    percents = drawn(run, tmp_path).trace("Returns")["x"]

    assert list(percents) == pytest.approx([100 * each for each in daily])


@pytest.mark.unit
def test_the_benchmark_is_overlaid_with_its_relative_statistics(
    prices: PriceCatalog, tmp_path: Path
) -> None:
    figure = drawn(btc_round_trip(prices), tmp_path, benchmark=BuyAndHold())

    overlay = figure.trace("BuyAndHold")
    assert overlay["xaxis"] == figure.trace("Strategy")["xaxis"]
    names = statistic_names(figure)
    assert "Alpha (365 days)" in names
    assert "Beta" in names


@pytest.mark.unit
def test_without_a_benchmark_there_is_no_overlay(
    prices: PriceCatalog, tmp_path: Path
) -> None:
    figure = drawn(btc_round_trip(prices), tmp_path)

    equity_panel = figure.trace("Strategy")["xaxis"]
    assert [
        each["name"] for each in figure.traces if each.get("xaxis") == equity_panel
    ] == ["Strategy"]
    names = statistic_names(figure)
    assert "Beta" not in names
    assert not [each for each in names if each.startswith("Alpha")]


@pytest.mark.unit
def test_the_rolling_sharpe_is_annualized_by_the_asset_calendar(
    prices: PriceCatalog, tmp_path: Path
) -> None:
    days = 80
    values = wavy(days)
    daily_run = replace(
        run_on([BTC], START, START + days * DAY), equity_interval_ms=86_400_000
    )
    run = PricedRun(
        daily_run,
        RunTables(
            equity({START + k * DAY: value for k, value in enumerate(values)}),
            pd.DataFrame(),
            pd.DataFrame(),
            "USDT",
        ),
        prices.catalog,
    )
    returns = pd.Series(values).pct_change().iloc[1:]
    rolling = returns.rolling(60)
    expected = pd.Series(rolling.mean() / rolling.std()).dropna() * math.sqrt(365)

    figure = drawn(run, tmp_path)

    sharpe = figure.trace("Rolling Sharpe")["y"]
    assert list(sharpe[~np.isnan(sharpe)]) == pytest.approx(list(expected))
    assert len([each for each in figure.titles if "Rolling Sharpe" in each]) == 1


@pytest.mark.unit
def test_the_cost_waterfall_steps_from_gross_to_net(
    prices: PriceCatalog, tmp_path: Path
) -> None:
    run = btc_round_trip(prices)
    costs = costs_and_exposure(run).total.costs

    [waterfall] = drawn(run, tmp_path).of_type("waterfall")

    assert list(waterfall["x"]) == ["Gross PnL", "Fees", "Carry", "Net PnL"]
    assert list(waterfall["measure"]) == ["absolute", "relative", "relative", "total"]
    assert list(waterfall["y"]) == pytest.approx(astuple(costs))
    assert costs.fees == pytest.approx(-2.0)
    assert costs.carry == pytest.approx(-5.0)


@pytest.mark.unit
def test_the_instrument_breakdown_has_a_row_per_traded_instrument(
    prices: PriceCatalog, tmp_path: Path
) -> None:
    run = btc_and_eth(prices)
    activities = costs_and_exposure(run).by_instrument

    rows = instrument_rows(drawn(run, tmp_path))

    assert set(rows) == {str(BTC), str(ETH)}
    for instrument, win_rate in ((BTC, 1.0), (ETH, 0.0)):
        row, activity = rows[str(instrument)], activities[str(instrument)]
        assert float(row["Net PnL"]) == pytest.approx(activity.costs.net, abs=1e-4)
        assert float(row["Fees"]) == pytest.approx(activity.costs.fees, abs=1e-4)
        assert float(row["Carry"]) == pytest.approx(activity.costs.carry, abs=1e-4)
        assert float(row["Turnover"]) == pytest.approx(activity.turnover, abs=1e-4)
        assert float(row["Time in Market"]) == pytest.approx(
            activity.exposure.time_in_market, abs=1e-4
        )
        assert row["Trades"] == "2"
        assert float(row["Win Rate"]) == pytest.approx(win_rate)
    assert float(rows[str(BTC)]["Carry"]) == pytest.approx(-5.0)
