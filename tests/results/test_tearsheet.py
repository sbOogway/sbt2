from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from nautilus_trader.model import InstrumentId
from plotted import Plotted, plotted
from price_catalog import BTC, PriceCatalog, run_on

from sbt2.results import PricedRun, RunTables, tearsheet

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
    """1 BTC bought at 50000 and sold at 51000 within two days."""
    end = START + 2 * DAY
    prices.add_marks(BTC, {START + k * HOUR: 50_000.0 + 20 * k for k in range(48)})
    tables = RunTables(
        equity(hourly(wavy(48))),
        pd.DataFrame(
            [fill(BTC, START + HOUR, 1, 50_000.0), fill(BTC, START + DAY, -1, 51_000.0)]
        ),
        pd.DataFrame(),
        "USDT",
        pd.DataFrame([closed(BTC, 998.0, START + DAY)], index=pd.Index(["P-1"])),
    )
    return PricedRun(run_on([BTC], START, end), tables, prices.catalog)


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


@pytest.mark.unit
def test_the_tearsheet_is_written_to_the_given_path(
    prices: PriceCatalog, tmp_path: Path
) -> None:
    target = tmp_path / "report" / "tearsheet.html"
    target.parent.mkdir()

    tearsheet(btc_round_trip(prices), target)

    assert "Plotly.newPlot(" in target.read_text()


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
    day_ends = [values[0], values[23], values[47], values[71]]
    daily = [after / before - 1 for before, after in pairwise(day_ends)]

    percents = drawn(run, tmp_path).trace("Returns")["x"]

    assert list(percents) == pytest.approx([100 * each for each in daily])
