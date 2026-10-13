from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from sbt2.core.results import RunTables, trade_table

START = datetime(2024, 1, 1, tzinfo=UTC)
PUT = "BTC-12JAN24-40000-P.DERIBIT"
CALL = "BTC-12JAN24-50000-C.DERIBIT"
NO_FEE = "0.00000000 BTC"


def fill(
    order: str,
    instrument: str,
    side: str,
    quantity: str,
    price: str,
    at: datetime,
    fee: str = NO_FEE,
) -> dict[str, object]:
    return {
        "venue_order_id": order,
        "instrument_id": instrument,
        "order_side": side,
        "last_qty": quantity,
        "last_px": price,
        "commission": fee,
        "ts_event": at,
    }


def order(venue_order_id: str, *tags: str) -> dict[str, object]:
    return {"venue_order_id": venue_order_id, "tags": list(tags)}


def tables(
    fills: list[dict[str, object]], orders: list[dict[str, object]]
) -> RunTables:
    return RunTables(
        pd.DataFrame(),
        pd.DataFrame(fills),
        pd.DataFrame(),
        "BTC",
        orders=pd.DataFrame(orders),
    )


def strangle(opened: datetime, closed: datetime) -> RunTables:
    """Combo C1 sells a put at 0.05 and a call at 0.04, and buys both back at 0.02
    and 0.01."""
    return tables(
        [
            fill("o1", PUT, "SELL", "1.0", "0.05", opened),
            fill("o2", CALL, "SELL", "1.0", "0.04", opened),
            fill("o3", PUT, "BUY", "1.0", "0.02", closed),
            fill("o4", CALL, "BUY", "1.0", "0.01", closed),
        ],
        [order(f"o{k}", "COMBO:C1") for k in range(1, 5)],
    )


def only(trades: pd.DataFrame) -> pd.Series:
    assert len(trades) == 1
    return trades.iloc[0]


@pytest.mark.unit
def test_the_fills_of_a_combo_make_one_trade() -> None:
    run = strangle(START, START + timedelta(days=1))

    trade = only(trade_table(run))

    assert trade["trade_id"] == "C1"
    assert trade["pl"] == pytest.approx(0.06)
    assert trade["credit"] == pytest.approx(0.09)
    assert trade["ts_opened"] == START
    assert trade["ts_closed"] == START + timedelta(days=1)


@pytest.mark.unit
def test_a_combo_still_open_is_not_a_trade() -> None:
    run = tables(
        [fill("o1", PUT, "SELL", "1.0", "0.05", START)], [order("o1", "COMBO:C1")]
    )

    assert trade_table(run).empty


@pytest.mark.unit
def test_a_trades_pl_is_after_fees_and_the_delivery_fee() -> None:
    day = START + timedelta(days=1)
    run = tables(
        [
            fill("o1", PUT, "SELL", "1.0", "0.05", START, "0.00030000 BTC"),
            fill("o2", PUT, "BUY", "1.0", "0.02", day, "0.00010000 BTC"),
        ],
        [order("o1", "COMBO:C1"), order("o2", "SETTLEMENT", "COMBO:C1")],
    )

    trade = only(trade_table(run))

    assert trade["pl"] == pytest.approx(0.03 - 0.0004)


@pytest.mark.unit
def test_a_settlement_shared_by_two_combos_is_split_by_their_quantities() -> None:
    day = START + timedelta(days=1)
    run = tables(
        [
            fill("o1", PUT, "SELL", "1.0", "0.10", START),
            fill("o2", PUT, "SELL", "3.0", "0.10", START),
            fill("o3", PUT, "BUY", "4.0", "0.02", day, "0.00040000 BTC"),
        ],
        [
            order("o1", "COMBO:C1"),
            order("o2", "COMBO:C2"),
            order("o3", "SETTLEMENT", "COMBO:C1", "COMBO:C2"),
        ],
    )

    trades = trade_table(run).set_index("trade_id")

    assert trades.loc["C1", "pl"] == pytest.approx(0.10 - 0.02 - 0.0001)
    assert trades.loc["C2", "pl"] == pytest.approx(3 * (0.10 - 0.02) - 0.0003)


@pytest.mark.unit
def test_a_trades_pl_percent_of_credit_and_days_held() -> None:
    run = tables(
        [
            fill("o1", PUT, "SELL", "1.0", "0.10", START),
            fill("o2", PUT, "BUY", "1.0", "0.05", START + timedelta(hours=60)),
        ],
        [order("o1", "COMBO:C1"), order("o2", "COMBO:C1")],
    )

    trade = only(trade_table(run))

    assert trade["pl_percent"] == pytest.approx(50.0)
    assert trade["days_held"] == pytest.approx(2.5)


@pytest.mark.unit
def test_a_trades_pl_in_usd_uses_the_index_at_its_close() -> None:
    closed = START + timedelta(days=1)
    index = pd.Series(
        [30_000.0, 40_000.0, 50_000.0],
        index=pd.DatetimeIndex([START, closed - timedelta(hours=1), closed]),
    )

    trade = only(trade_table(strangle(START, closed), {PUT: index}))

    assert trade["index_at_close"] == 50_000.0
    assert trade["pl_usd"] == pytest.approx(0.06 * 50_000.0)


@pytest.mark.unit
def test_a_trade_without_an_index_has_no_usd_figure() -> None:
    trades = trade_table(strangle(START, START + timedelta(days=1)))

    assert bool(trades["index_at_close"].isna().all())
    assert bool(trades["pl_usd"].isna().all())


@pytest.mark.unit
def test_a_run_without_combos_counts_its_positions_as_trades() -> None:
    day = START + timedelta(days=1)
    fills = [
        fill("o1", PUT, "SELL", "1.0", "0.10", START),
        fill("o2", PUT, "BUY", "1.0", "0.04", day),
        fill("o3", CALL, "SELL", "1.0", "0.08", day),
    ]
    for each, position in zip(fills, ["P1", "P1", "P2"], strict=True):
        each["position_id"] = position
    positions = pd.DataFrame(
        {
            "instrument_id": [PUT, CALL],
            "entry": ["SELL", "SELL"],
            "ts_opened": [START, day],
            "ts_closed": [day, pd.NaT],
            "duration_ns": [86_400 * 10**9, 0],
            "realized_pnl": ["0.06000000 BTC", "0.00000000 BTC"],
        },
        index=pd.Index(["P1", "P2"], name="position_id"),
    )
    run = RunTables(
        pd.DataFrame(), pd.DataFrame(fills), pd.DataFrame(), "BTC", positions
    )

    trade = only(trade_table(run))

    assert trade["trade_id"] == "P1"
    assert trade["pl"] == pytest.approx(0.06)
    assert trade["credit"] == pytest.approx(0.10)
    assert trade["pl_percent"] == pytest.approx(60.0)
    assert trade["days_held"] == pytest.approx(1.0)


@pytest.mark.unit
def test_a_run_without_fills_has_an_empty_trade_table_with_its_columns() -> None:
    trades = trade_table(
        RunTables(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), "BTC")
    )

    assert trades.empty
    assert "pl_usd" in trades.columns
