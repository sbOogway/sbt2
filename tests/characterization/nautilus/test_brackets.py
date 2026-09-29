from typing import Any

import pytest
from feed_kit import FEEDS, PricePath, StepStrategy, fills, minute, run_on_feed
from kit import INSTRUMENT_ID
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.model import ClientOrderId, OrderSide, OrderStatus, Price, Quantity

ENTRY_PRICE = "50000.0"
TAKE_PROFIT = "51000.0"
STOP_LOSS = "49000.0"


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
