from dataclasses import astuple
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from price_catalog import BTC, PriceCatalog, run_on

from sbt2.results import PricedRun, RunTables, costs_and_exposure

START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)


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


def fill(at: datetime, quantity: float, price: float) -> dict:
    """A fill of BTC without fees; a negative quantity sells."""
    return {
        "instrument_id": str(BTC),
        "order_side": "BUY" if quantity > 0 else "SELL",
        "last_qty": str(abs(quantity)),
        "last_px": str(price),
        "commission": "0 USDT",
        "ts_event": pd.Timestamp(at),
    }


def paying(row: dict, fee: float) -> dict:
    return {**row, "commission": f"{fee} USDT"}


def funding(at: datetime, amount: float) -> dict:
    return {
        "instrument_id": str(BTC),
        "pnl_change": f"{amount} USDT",
        "ts_event": pd.Timestamp(at),
    }


def tables(
    points: dict[datetime, float], fills: list[dict], carry: list[dict]
) -> RunTables:
    return RunTables(equity(points), pd.DataFrame(fills), pd.DataFrame(carry), "USDT")


def round_trip_paying(carry: float) -> RunTables:
    """1 BTC bought and sold at 50000 within the part, 10 USDT fees."""
    return tables(
        {START: 10_000.0, START + 2 * HOUR: 10_100.0},
        [
            paying(fill(START + HOUR, 1, 50_000.0), 5.0),
            paying(fill(START + 90 * MINUTE, -1, 50_000.0), 5.0),
        ],
        [funding(START + HOUR, carry)],
    )


@pytest.mark.unit
def test_the_cost_waterfall_goes_from_gross_through_fees_and_carry_to_net(
    prices: PriceCatalog,
) -> None:
    prices.add_marks(BTC, {START: 50_000.0})
    run = PricedRun(
        run_on([BTC], START, START + 2 * HOUR), round_trip_paying(-5.0), prices.catalog
    )

    costs = costs_and_exposure(run).total.costs

    assert astuple(costs) == pytest.approx((115.0, -10.0, -5.0, 100.0))


@pytest.mark.unit
def test_received_carry_raises_the_net(prices: PriceCatalog) -> None:
    prices.add_marks(BTC, {START: 50_000.0})
    run = PricedRun(
        run_on([BTC], START, START + 2 * HOUR), round_trip_paying(3.0), prices.catalog
    )

    costs = costs_and_exposure(run).total.costs

    assert costs.carry == pytest.approx(3.0)
    assert costs.gross + costs.fees + costs.carry == pytest.approx(costs.net)
    assert costs.gross == pytest.approx(107.0)
