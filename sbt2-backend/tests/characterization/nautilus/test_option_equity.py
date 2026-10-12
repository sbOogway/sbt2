import pytest
from nautilus_trader.model import OrderSide
from nautilus_trader.portfolio import PortfolioConfig
from option_kit import BTC, VENUE, Market, mark, run_orders, trade

LAST_HOUR = 10
HOURLY = 3_600_000
MARKET = Market(
    portfolio=PortfolioConfig(use_mark_prices=True, snapshot_interval_ms=HOURLY)
)
DATA = [
    trade(0, "0.0500"),
    *(mark(hour, f"{0.05 + 0.003 * hour:.4f}") for hour in range(LAST_HOUR + 1)),
]


def final_equity(side: OrderSide) -> float:
    engine, _ = run_orders(DATA, {2: (side, "1.0")}, market=MARKET)
    account_id = engine.cache.account_id(VENUE)
    assert account_id is not None
    [equity] = engine.portfolio.snapshots(account_id)[-1].total_equity
    assert equity.currency == BTC
    return equity.as_double()


@pytest.mark.characterization
@pytest.mark.integration
def test_equity_of_a_long_option_counts_the_premium_twice() -> None:
    # The true equity is 1 - 0.05 + 0.08 = 1.03.
    assert final_equity(OrderSide.BUY) == pytest.approx(0.98)


@pytest.mark.characterization
@pytest.mark.integration
def test_equity_of_a_short_option_counts_the_premium_twice() -> None:
    # The true equity is 1 + 0.05 - 0.08 = 0.97.
    assert final_equity(OrderSide.SELL) == pytest.approx(1.02)
