from dataclasses import astuple, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model import InstrumentId, MarkPriceUpdate
from price_catalog import BTC, ETH, PriceCatalog, perpetual_with, run_on

from sbt2.data import Gap
from sbt2.results import (
    InverseInstrumentError,
    MissingPricesError,
    PricedRun,
    RunTables,
    costs_and_exposure,
)

START = datetime(2024, 1, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
MINUTE = timedelta(minutes=1)
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


def of(instrument: InstrumentId, row: dict) -> dict:
    return {**row, "instrument_id": str(instrument)}


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


def trade(held: timedelta) -> dict:
    """A closed BTC trade held for ``held``."""
    return {
        "instrument_id": str(BTC),
        "entry": "BUY",
        "ts_closed": pd.Timestamp(START + held),
        "duration_ns": int(held.total_seconds() * 1e9),
        "realized_pnl": "0 USDT",
    }


def still_open(row: dict) -> dict:
    return {**row, "ts_closed": pd.NaT}


def with_trades(run: RunTables, trades: list[dict]) -> RunTables:
    return replace(run, positions=pd.DataFrame(trades))


def flat(value: float, end: datetime) -> dict[datetime, float]:
    return {START: value, end: value}


def exposure_of(run: RunTables, prices: PriceCatalog, end: datetime):
    return costs_and_exposure(
        PricedRun(run_on([BTC, ETH], START, end), run, prices.catalog)
    ).total.exposure


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


@pytest.mark.unit
def test_leverage_follows_the_position_at_the_valuation_price(
    prices: PriceCatalog,
) -> None:
    end = START + 3 * HOUR
    prices.add_marks(BTC, {START: 50_000.0, START + 150 * MINUTE: 55_000.0})
    run = tables(flat(10_000.0, end), [fill(START + HOUR, 1, 50_000.0)], [])

    exposure = exposure_of(run, prices, end)

    assert list(exposure.gross_leverage) == pytest.approx([0.0, 5.0, 5.0, 5.5])
    assert exposure.net_leverage.equals(exposure.gross_leverage)
    assert list(exposure.gross_leverage.index) == [START + k * HOUR for k in range(4)]


@pytest.mark.unit
def test_long_and_short_offset_in_net_but_add_in_gross(prices: PriceCatalog) -> None:
    end = START + HOUR
    prices.add_marks(BTC, {START: 50_000.0})
    prices.add_marks(ETH, {START: 2_500.0})
    run = tables(
        flat(10_000.0, end),
        [fill(START, 0.1, 50_000.0), of(ETH, fill(START, -2, 2_500.0))],
        [],
    )

    exposure = exposure_of(run, prices, end)

    assert exposure.gross_leverage[end] == pytest.approx(1.0)
    assert exposure.net_leverage[end] == pytest.approx(0.0)


@pytest.mark.unit
def test_time_in_market_is_the_share_of_grid_steps_with_a_position(
    prices: PriceCatalog,
) -> None:
    end = START + 4 * HOUR
    prices.add_marks(BTC, {START: 50_000.0})
    run = tables(
        flat(10_000.0, end),
        [fill(START + HOUR, 1, 50_000.0), fill(START + 3 * HOUR, -1, 50_000.0)],
        [],
    )

    assert exposure_of(run, prices, end).time_in_market == pytest.approx(0.5)


@pytest.mark.unit
def test_exposure_carries_prices_across_known_gaps(prices: PriceCatalog) -> None:
    end = START + 3 * DAY
    prices.add_marks(BTC, {START: 50_000.0, START + 2 * DAY: 60_000.0})
    gap = Gap(BTC, MarkPriceUpdate, (START + DAY).date())
    run = tables(flat(10_000.0, end), [fill(START + HOUR, 1, 50_000.0)], [])

    exposure = costs_and_exposure(
        PricedRun(run_on([BTC], START, end), run, prices.catalog, frozenset({gap}))
    ).total.exposure

    assert exposure.gross_leverage[START + 36 * HOUR] == pytest.approx(5.0)
    assert exposure.gross_leverage[START + 2 * DAY] == pytest.approx(6.0)


@pytest.mark.unit
def test_missing_valuation_prices_fail(prices: PriceCatalog) -> None:
    end = START + 2 * DAY
    prices.add_marks(BTC, {START: 50_000.0})
    run = tables(flat(10_000.0, end), [fill(START + HOUR, 1, 50_000.0)], [])

    with pytest.raises(
        MissingPricesError,
        match="MarkPriceUpdate for BTCUSDT-LINEAR.BYBIT on 2024-01-02",
    ):
        exposure_of(run, prices, end)


@pytest.mark.unit
def test_an_inverse_instrument_fails(prices: PriceCatalog) -> None:
    end = START + HOUR
    inverse = InstrumentId.from_str("BTCUSD-INVERSE.BYBIT")
    prices.add_instrument(
        perpetual_with(
            inverse, is_inverse=True, quote_currency="USD", settlement_currency="BTC"
        )
    )
    prices.add_marks(inverse, {START: 50_000.0})
    run = tables(flat(10_000.0, end), [of(inverse, fill(START, 1, 50_000.0))], [])

    with pytest.raises(InverseInstrumentError, match="BTCUSD-INVERSE.BYBIT"):
        costs_and_exposure(
            PricedRun(run_on([inverse], START, end), run, prices.catalog)
        )


@pytest.mark.unit
def test_notional_counts_the_contract_multiplier(prices: PriceCatalog) -> None:
    end = START + HOUR
    prices.add_instrument(perpetual_with(BTC, multiplier="10"))
    prices.add_marks(BTC, {START: 500.0})
    run = tables(flat(10_000.0, end), [fill(START, 1, 500.0)], [])

    assert exposure_of(run, prices, end).gross_leverage[end] == pytest.approx(0.5)


@pytest.mark.unit
def test_holding_time_comes_from_the_closed_trades(prices: PriceCatalog) -> None:
    end = START + 4 * HOUR
    run = with_trades(
        tables(flat(10_000.0, end), [], []),
        [trade(HOUR), trade(3 * HOUR), still_open(trade(10 * HOUR))],
    )

    holding = costs_and_exposure(
        PricedRun(run_on([BTC], START, end), run, prices.catalog)
    ).total.holding_time

    assert holding is not None
    assert holding.mean == 2 * HOUR
    assert holding.median == 2 * HOUR
