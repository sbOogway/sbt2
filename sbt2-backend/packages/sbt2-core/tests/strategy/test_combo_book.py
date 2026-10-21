from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count

import pytest
from nautilus_trader.core import UUID4
from nautilus_trader.model import (
    AccountId,
    ClientOrderId,
    CryptoOption,
    Currency,
    InstrumentId,
    LiquiditySide,
    OptionKind,
    OrderFilled,
    OrderSide,
    OrderType,
    Price,
    Quantity,
    StrategyId,
    TradeId,
    TraderId,
    VenueOrderId,
)
from option_catalog import Terms, listed_option

from sbt2.core.strategy import Combo, Leg
from sbt2.core.strategy.combo_book import Change, ComboBook

NOW = datetime(2024, 1, 2, tzinfo=UTC)
_ids = count(1)


def put(days: int) -> CryptoOption:
    name = f"BTC-{days}D-45000-P.DERIBIT"
    terms = Terms(OptionKind.PUT, NOW + timedelta(days=days), "45000")
    return listed_option(InstrumentId.from_str(name), terms)


NEAR = put(1)
FAR = put(30)


@dataclass(frozen=True)
class Order:
    client_order_id: ClientOrderId


def order() -> Order:
    return Order(ClientOrderId(f"O-{next(_ids)}"))


def fill(sent: Order, contract: CryptoOption, quantity: str) -> OrderFilled:
    return OrderFilled(
        TraderId("TESTER-001"),
        StrategyId("S-001"),
        contract.id,
        sent.client_order_id,
        VenueOrderId(f"V-{next(_ids)}"),
        AccountId("DERIBIT-001"),
        TradeId(f"T-{next(_ids)}"),
        OrderSide.BUY,
        OrderType.MARKET,
        Quantity.from_str(quantity),
        Price.from_str("0.01"),
        Currency.from_str("BTC"),
        LiquiditySide.TAKER,
        UUID4(),
        0,
        0,
        False,
    )


def opened(book: ComboBook, *legs: Leg) -> Combo:
    """A combo of ``legs`` whose leg orders all filled."""
    combo = replace(Combo("test", legs), id=book.next_id())
    orders = [order() for _ in legs]
    book.opening(combo, orders)
    for sent, leg in zip(orders, legs, strict=True):
        book.hear(fill(sent, leg.contract, str(leg.quantity)))
    return combo


def ids(changes: list[tuple[Change, Combo]]) -> list[tuple[Change, str | None]]:
    return [(change, combo.id) for change, combo in changes]


@pytest.mark.unit
def test_a_settlement_closes_every_combo_that_holds_the_contract() -> None:
    book = ComboBook()
    long = opened(book, Leg(NEAR, OrderSide.BUY, Decimal(2)))
    short = opened(book, Leg(NEAR, OrderSide.SELL, Decimal(1)))
    settlement = order()
    book.settling(NEAR.id, settlement)

    changes = book.hear(fill(settlement, NEAR, "1"))

    assert ids(changes) == [(Change.SETTLED, long.id), (Change.SETTLED, short.id)]
    assert book.opened() == ()


@pytest.mark.unit
def test_a_settlement_split_into_fills_settles_each_combo_once() -> None:
    book = ComboBook()
    first = opened(book, Leg(NEAR, OrderSide.SELL, Decimal(1)))
    second = opened(book, Leg(NEAR, OrderSide.SELL, Decimal(1)))
    settlement = order()
    book.settling(NEAR.id, settlement)

    changes = book.hear(fill(settlement, NEAR, "1"))
    later = book.hear(fill(settlement, NEAR, "1"))

    assert ids(changes) == [(Change.SETTLED, first.id), (Change.SETTLED, second.id)]
    assert later == []


@pytest.mark.unit
def test_combos_that_net_to_zero_settle_without_an_order() -> None:
    book = ComboBook()
    long = opened(book, Leg(NEAR, OrderSide.BUY, Decimal(1)))
    short = opened(book, Leg(NEAR, OrderSide.SELL, Decimal(1)))

    changes = book.settle(NEAR.id)

    assert ids(changes) == [(Change.SETTLED, long.id), (Change.SETTLED, short.id)]
    assert book.opened() == ()


@pytest.mark.unit
def test_a_settlement_closes_only_the_expiring_leg() -> None:
    book = ComboBook()
    calendar = opened(
        book,
        Leg(NEAR, OrderSide.SELL, Decimal(1)),
        Leg(FAR, OrderSide.BUY, Decimal(1)),
    )
    settlement = order()
    book.settling(NEAR.id, settlement)

    changes = book.hear(fill(settlement, NEAR, "1"))

    assert changes == []
    assert calendar.id is not None
    assert book.remaining(calendar.id) == {FAR.id: Decimal(1)}
