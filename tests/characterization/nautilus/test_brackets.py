from typing import Any

import pytest
from feed_kit import FEEDS, PricePath, StepStrategy, fills, minute, run_on_feed
from kit import INSTRUMENT_ID
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.model import (
    ClientOrderId,
    OrderSide,
    OrderStatus,
    OrderType,
    Price,
    Quantity,
)

ENTRY_PRICE = "50000.0"
TAKE_PROFIT = "51000.0"
STOP_LOSS = "49000.0"
MOVED_STOP = "48000.0"
CHANGED_LIMIT = "49500.0"
LIMIT_ENTRY = "49500.0"
PARTIAL_DIP = PricePath([ENTRY_PRICE, "49400.0"], size_per_price="0.400")


class LongBracket(StepStrategy):
    def on_step(self, step: int) -> None:
        if step == 0:
            self.submit_bracket()

    def submit_bracket(self) -> None:
        orders = self.order_factory.bracket(
            INSTRUMENT_ID,
            OrderSide.BUY,
            Quantity.from_str("1.000"),
            tp_price=Price.from_str(TAKE_PROFIT),
            sl_trigger_price=Price.from_str(STOP_LOSS),
            **self.entry_terms(),
        )
        self.entry, self.stop_loss, self.take_profit = (
            order.client_order_id for order in orders
        )
        self.submit_order_list(orders)

    def entry_terms(self) -> dict[str, Any]:
        return {}


class LimitEntryBracket(LongBracket):
    def entry_terms(self) -> dict[str, Any]:
        return {
            "entry_order_type": OrderType.LIMIT,
            "entry_price": Price.from_str(LIMIT_ENTRY),
        }


def order(engine: BacktestEngine, client_order_id: ClientOrderId) -> Any:
    found = engine.cache.order(client_order_id)
    assert found is not None
    return found


@pytest.mark.characterization
@pytest.mark.integration
@pytest.mark.parametrize("feed", FEEDS)
def test_a_take_profit_fill_cancels_the_stop_loss(feed: str) -> None:
    strategy = LongBracket()
    path = PricePath([ENTRY_PRICE, "50500.0", "51200.0", "51500.0"])

    engine = run_on_feed(strategy, feed, path)

    assert fills(order(engine, strategy.take_profit)) == [
        (minute(2), TAKE_PROFIT, "1.000")
    ]
    assert order(engine, strategy.stop_loss).status == OrderStatus.CANCELED
    [position] = engine.cache.positions()
    assert position.is_closed


@pytest.mark.characterization
@pytest.mark.integration
# A bar that crosses the trigger fills the stop at the trigger; a trade that
# gaps through it fills the stop at the trade's price.
@pytest.mark.parametrize(
    ("feed", "stop_fill_price"),
    [("bars", STOP_LOSS), ("trades", "48800.0")],
)
def test_a_stop_loss_fill_cancels_the_take_profit(
    feed: str, stop_fill_price: str
) -> None:
    strategy = LongBracket()
    path = PricePath([ENTRY_PRICE, "49500.0", "48800.0", "48500.0"])

    engine = run_on_feed(strategy, feed, path)

    assert fills(order(engine, strategy.stop_loss)) == [
        (minute(2), stop_fill_price, "1.000")
    ]
    assert order(engine, strategy.take_profit).status == OrderStatus.CANCELED
    [position] = engine.cache.positions()
    assert position.is_closed


class MovedStop(StepStrategy):
    def on_step(self, step: int) -> None:
        if step == 0:
            self.submit_stop()
        if step == 1:
            self.modify_order(
                self.resting_stop, trigger_price=Price.from_str(MOVED_STOP)
            )

    def submit_stop(self) -> None:
        stop = self.order_factory.stop_market(
            INSTRUMENT_ID,
            OrderSide.SELL,
            Quantity.from_str("1.000"),
            Price.from_str(STOP_LOSS),
        )
        self.resting_stop = stop.client_order_id
        self.submit_order(stop)


@pytest.mark.characterization
@pytest.mark.integration
@pytest.mark.parametrize(
    ("feed", "stop_fill_price"),
    [("bars", MOVED_STOP), ("trades", "47800.0")],
)
def test_modify_order_moves_a_resting_stop(feed: str, stop_fill_price: str) -> None:
    strategy = MovedStop()
    path = PricePath([ENTRY_PRICE, "49800.0", "48800.0", "47800.0"])

    engine = run_on_feed(strategy, feed, path)

    stop = order(engine, strategy.resting_stop)
    assert stop.trigger_price == Price.from_str(MOVED_STOP)
    assert fills(stop) == [(minute(3), stop_fill_price, "1.000")]


class ChangedLimit(StepStrategy):
    def on_step(self, step: int) -> None:
        if step == 0:
            self.submit_limit()
        if step == 1:
            self.modify_order(
                self.resting_limit,
                quantity=Quantity.from_str("0.500"),
                price=Price.from_str(CHANGED_LIMIT),
            )

    def submit_limit(self) -> None:
        limit = self.order_factory.limit(
            INSTRUMENT_ID,
            OrderSide.BUY,
            Quantity.from_str("1.000"),
            Price.from_str("49000.0"),
        )
        self.resting_limit = limit.client_order_id
        self.submit_order(limit)


@pytest.mark.characterization
@pytest.mark.integration
@pytest.mark.parametrize("feed", FEEDS)
def test_modify_order_changes_a_resting_limit(feed: str) -> None:
    strategy = ChangedLimit()
    path = PricePath([ENTRY_PRICE, "49800.0", "49400.0", "49400.0"])

    engine = run_on_feed(strategy, feed, path)

    limit = order(engine, strategy.resting_limit)
    assert (limit.quantity, limit.price) == (
        Quantity.from_str("0.500"),
        Price.from_str(CHANGED_LIMIT),
    )
    assert fills(limit) == [(minute(2), CHANGED_LIMIT, "0.500")]


@pytest.mark.characterization
@pytest.mark.integration
@pytest.mark.parametrize("feed", FEEDS)
def test_a_partially_filled_entry_sizes_its_exits(feed: str) -> None:
    strategy = LimitEntryBracket()

    engine = run_on_feed(strategy, feed, PARTIAL_DIP)

    entry = order(engine, strategy.entry)
    assert entry.status == OrderStatus.PARTIALLY_FILLED
    assert fills(entry) == [(minute(1), LIMIT_ENTRY, "0.400")]
    exits = [order(engine, strategy.stop_loss), order(engine, strategy.take_profit)]
    assert [(each.status, str(each.quantity)) for each in exits] == [
        (OrderStatus.ACCEPTED, "1.000"),
        (OrderStatus.ACCEPTED, "1.000"),
    ]
