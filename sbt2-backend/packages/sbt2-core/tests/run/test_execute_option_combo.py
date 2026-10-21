from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from combo_strategies import OpenStrangle
from option_catalog import build_chain_catalog, build_ladder_catalog, chain_contract_id
from option_runs import run_options

from sbt2.core.results import ParquetResultStore

PUT = str(chain_contract_id("12JAN24", 40000, "P"))
CALL = str(chain_contract_id("12JAN24", 50000, "C"))
LIVE_PUT = str(chain_contract_id("12JAN24", 45000, "P"))
EXPIRING_PUT = str(chain_contract_id("2JAN24", 45000, "P"))
EXPIRING_CALL = str(chain_contract_id("2JAN24", 45000, "C"))


@pytest.fixture(scope="module")
def expiring(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("chain_catalog")
    build_chain_catalog(path)
    return path


@pytest.fixture(scope="module")
def falling(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("falling_catalog")
    build_ladder_catalog(path, mark_step=Decimal("-0.001"))
    return path


@pytest.fixture(scope="module")
def ladder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("ladder_catalog")
    build_ladder_catalog(path)
    return path


def tags_of_fills(store: ParquetResultStore, run_id: str) -> list[list[str]]:
    """The tags of the order of each fill."""
    orders = store.load(run_id, "orders").set_index("venue_order_id")["tags"]
    fills = store.load(run_id, "fills")
    return [list(orders[each]) for each in fills["venue_order_id"]]


@pytest.mark.integration
def test_a_strategy_opens_a_strangle_as_one_combo(tmp_path: Path, ladder: Path) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(tmp_path, ladder, "combo_strategies:OpenStrangle")

    fills = store.load(run_id, "fills")
    assert sorted(fills["instrument_id"]) == sorted([PUT, CALL])
    assert set(fills["order_side"]) == {"SELL"}
    [opened] = OpenStrangle.opened
    assert opened.id == "C1"
    assert opened.name == "short strangle"
    by_leg = {each.contract.id.value: each.price for each in opened.legs}
    prices = {
        row["instrument_id"]: Decimal(str(row["last_px"]))
        for row in fills.to_dict("records")
    }
    assert by_leg == prices
    assert opened.credit == sum(prices.values())
    assert tags_of_fills(store, run_id) == [["COMBO:C1"], ["COMBO:C1"]]
    [seen] = {ids for _, ids in OpenStrangle.seen[-1:]}
    assert seen == ("C1",)


@pytest.mark.integration
def test_a_combos_margin_is_that_of_its_legs(tmp_path: Path, ladder: Path) -> None:
    OpenStrangle.clear()

    run_options(tmp_path, ladder, "combo_strategies:OpenStrangle")

    [(margin, held)] = OpenStrangle.margins
    assert margin > 0
    assert margin == held


@pytest.mark.integration
def test_a_combo_closes_all_its_legs_together(tmp_path: Path, ladder: Path) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(
        tmp_path, ladder, "combo_strategies:CloseStrangleAtOnce"
    )

    fills = store.load(run_id, "fills").to_dict("records")
    assert [(each["instrument_id"], each["order_side"]) for each in fills] == [
        (PUT, "SELL"),
        (CALL, "SELL"),
        (PUT, "BUY"),
        (CALL, "BUY"),
    ]
    assert tags_of_fills(store, run_id) == [["COMBO:C1"]] * 4
    [closed] = OpenStrangle.closed
    assert closed.id == "C1"
    assert OpenStrangle.settled == []
    assert OpenStrangle.seen[-1][1] == ()
    assert set(store.load(run_id, "positions")["side"]) == {"FLAT"}


def closing(store: ParquetResultStore, run_id: str) -> tuple[datetime, Decimal]:
    """The time of the closing fills and the P/L in percent of the credit they
    realise against the entry fills."""
    fills = store.load(run_id, "fills")
    paid = {side: Decimal(0) for side in ("SELL", "BUY")}
    for fill in fills.to_dict("records"):
        paid[fill["order_side"]] += Decimal(str(fill["last_px"]))
    [at] = set(fills["ts_event"][fills["order_side"] == "BUY"])
    moment = datetime.fromtimestamp(pd.Timestamp(at).value / 10**9, UTC)
    return moment, (paid["SELL"] - paid["BUY"]) / paid["SELL"] * 100


def percent_before(tick: datetime) -> Decimal:
    [before] = [
        each
        for when, each in OpenStrangle.percents
        if when == tick - timedelta(hours=1)
    ]
    return before


@pytest.mark.integration
def test_a_combo_closes_at_its_profit_target(tmp_path: Path, falling: Path) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(
        tmp_path, falling, "combo_strategies:CloseStrangleAtProfit"
    )

    at, realised = closing(store, run_id)
    assert realised >= 20
    assert percent_before(at) < 20
    assert [each.id for each in OpenStrangle.closed] == ["C1"]


@pytest.mark.integration
def test_a_combo_closes_at_its_loss_target(tmp_path: Path, ladder: Path) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(
        tmp_path, ladder, "combo_strategies:CloseStrangleAtLoss"
    )

    at, realised = closing(store, run_id)
    assert realised <= -20
    assert percent_before(at) > -20
    assert [each.id for each in OpenStrangle.closed] == ["C1"]


@pytest.mark.integration
def test_a_combo_closes_at_its_dte(tmp_path: Path, ladder: Path) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(tmp_path, ladder, "combo_strategies:CloseStrangleAtDte")

    at, _ = closing(store, run_id)
    assert at == datetime(2024, 1, 2, 20, tzinfo=UTC)
    assert [each.id for each in OpenStrangle.closed] == ["C1"]


@pytest.mark.integration
def test_a_combo_held_to_expiry_settles_all_its_legs(
    tmp_path: Path, expiring: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(
        tmp_path, expiring, "combo_strategies:HoldStraddleToExpiry"
    )

    fills = store.load(run_id, "fills").to_dict("records")
    assert [each["order_side"] for each in fills] == ["SELL", "SELL", "BUY", "BUY"]
    assert tags_of_fills(store, run_id)[2:] == [["SETTLEMENT", "COMBO:C1"]] * 2
    [settled] = OpenStrangle.settled
    assert settled.id == "C1"
    assert OpenStrangle.closed == []
    assert OpenStrangle.seen[-1][1] == ()


@pytest.mark.integration
def test_opposite_combos_on_one_contract_both_settle_at_expiry(
    tmp_path: Path, expiring: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(
        tmp_path, expiring, "combo_strategies:HoldOppositeStraddles"
    )

    assert sorted(each.id for each in OpenStrangle.settled) == ["C1", "C2"]
    assert OpenStrangle.seen[-1][1] == ()
    settling = [
        (each["instrument_id"], each["order_side"], Decimal(each["last_qty"]))
        for each, tags in zip(
            store.load(run_id, "fills").to_dict("records"),
            tags_of_fills(store, run_id),
            strict=True,
        )
        if "SETTLEMENT" in tags
    ]
    assert sorted(settling) == [
        (EXPIRING_CALL, "SELL", Decimal(1)),
        (EXPIRING_PUT, "SELL", Decimal(1)),
    ]


@pytest.mark.integration
def test_a_combo_beyond_the_free_equity_is_refused_as_a_whole(
    tmp_path: Path, ladder: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(tmp_path, ladder, "combo_strategies:OpenTenStrangles")

    assert OpenStrangle.refused == [PUT]
    assert store.load(run_id, "fills").empty
    assert OpenStrangle.opened == []
    assert OpenStrangle.seen[-1][1] == ()


@pytest.mark.integration
def test_a_combo_with_a_rejected_leg_unwinds_its_filled_legs(
    tmp_path: Path, expiring: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(
        tmp_path, expiring, "combo_strategies:OpenStrangleWithExpiredCall"
    )

    fills = store.load(run_id, "fills").to_dict("records")
    assert [(each["instrument_id"], each["order_side"]) for each in fills] == [
        (LIVE_PUT, "SELL"),
        (LIVE_PUT, "BUY"),
    ]
    assert tags_of_fills(store, run_id) == [["COMBO:C1"]] * 2
    [(failed, reason)] = OpenStrangle.failed
    assert failed.id == "C1"
    assert "CLOSED" in reason
    assert OpenStrangle.opened == []
    assert OpenStrangle.seen[-1][1] == ()
    assert set(store.load(run_id, "positions")["side"]) == {"FLAT"}


@pytest.mark.integration
def test_an_order_on_an_unknown_instrument_is_refused_with_a_reason(
    tmp_path: Path, ladder: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(
        tmp_path, ladder, "combo_strategies:OpenStrangleWithUnknownCall"
    )

    [reason] = OpenStrangle.reasons
    assert "BTC-12JAN24-52000-C.DERIBIT" in reason
    assert "cannot be priced" in reason
    assert store.load(run_id, "fills").empty
