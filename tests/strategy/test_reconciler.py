from decimal import Decimal

from nautilus_trader.model import InstrumentId

from sbt2.strategy import (
    Cancel,
    PlaceMarket,
    TargetPosition,
    WorkingOrder,
    reconcile,
)

BTC = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
ETH = InstrumentId.from_str("ETHUSDT-PERP.BYBIT")


def target(quantity: str, instrument_id: InstrumentId = BTC) -> TargetPosition:
    return TargetPosition(instrument_id, Decimal(quantity))


def working(
    order_id: str, quantity: str, instrument_id: InstrumentId = BTC
) -> WorkingOrder:
    return WorkingOrder(order_id, instrument_id, Decimal(quantity))


def place(quantity: str, instrument_id: InstrumentId = BTC) -> PlaceMarket:
    return PlaceMarket(instrument_id, Decimal(quantity))


def test_places_the_difference_between_target_and_real_position() -> None:
    actions = reconcile([target("1.5")], {BTC: Decimal("0.5")}, [])

    assert actions == [place("1.0")]


def test_missing_position_counts_as_flat() -> None:
    assert reconcile([target("-2")], {}, []) == [place("-2")]


def test_target_already_held_needs_no_action() -> None:
    assert reconcile([target("1")], {BTC: Decimal(1)}, []) == []


def test_instrument_without_a_target_is_left_alone() -> None:
    actions = reconcile([], {BTC: Decimal(1)}, [working("O-1", "1")])

    assert actions == []


def test_working_orders_towards_the_target_count_as_placed() -> None:
    actions = reconcile([target("3")], {BTC: Decimal(0)}, [working("O-1", "1")])

    assert actions == [place("2")]


def test_working_orders_that_reach_the_target_need_no_action() -> None:
    actions = reconcile([target("2")], {}, [working("O-1", "1"), working("O-2", "1")])

    assert actions == []


def test_working_orders_on_the_wrong_side_are_canceled() -> None:
    actions = reconcile([target("1")], {}, [working("O-1", "-1")])

    assert actions == [Cancel("O-1"), place("1")]


def test_working_orders_that_overshoot_are_all_canceled() -> None:
    actions = reconcile([target("1")], {}, [working("O-1", "1"), working("O-2", "1")])

    assert actions == [Cancel("O-1"), Cancel("O-2"), place("1")]


def test_flat_target_cancels_working_orders_and_closes_the_position() -> None:
    actions = reconcile([target("0")], {BTC: Decimal(2)}, [working("O-1", "1")])

    assert actions == [Cancel("O-1"), place("-2")]


def test_last_target_for_an_instrument_wins() -> None:
    actions = reconcile([target("1"), target("3")], {}, [])

    assert actions == [place("3")]


def test_instruments_are_reconciled_independently() -> None:
    actions = reconcile(
        [target("1"), target("-1", ETH)],
        {ETH: Decimal(1)},
        [working("O-1", "1", ETH)],
    )

    assert actions == [place("1"), Cancel("O-1"), place("-2", ETH)]
