import pytest
from nautilus_trader.model import OrderSide
from option_kit import BTC, VENUE, btc, run_orders, trade

BUY = (OrderSide.BUY, "1.0")
SELL = (OrderSide.SELL, "1.0")


@pytest.mark.characterization
@pytest.mark.integration
def test_an_option_round_trip_realises_its_pnl_linearly_in_the_coin() -> None:
    data = [trade(0, "0.0500"), trade(5, "0.0600"), trade(30, "0.0700")]

    engine, _ = run_orders(data, {2: BUY, 10: SELL})

    [position] = engine.cache.positions()
    assert position.is_closed
    assert position.realized_pnl == btc("0.01")


@pytest.mark.characterization
@pytest.mark.integration
def test_a_long_option_pays_its_premium_from_the_balance() -> None:
    engine, _ = run_orders([trade(0, "0.0500"), trade(5, "0.0600")], {2: BUY})

    account = engine.cache.account_for_venue(VENUE)
    assert account is not None
    assert account.balance_total(BTC) == btc("0.95")
