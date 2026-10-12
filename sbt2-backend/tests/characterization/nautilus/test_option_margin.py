from decimal import Decimal

import pytest
from nautilus_trader.model import OrderSide
from option_kit import BTC, VENUE, Market, btc, option, run_orders, trade

SELL = (OrderSide.SELL, "1.0")
DATA = [trade(0, "0.0500"), trade(5, "0.0600")]


@pytest.mark.characterization
@pytest.mark.integration
def test_an_option_has_no_margin_rates_by_default() -> None:
    engine, _ = run_orders(DATA, {2: SELL})

    account = engine.cache.account_for_venue(VENUE)
    assert account is not None
    assert account.balance_locked(BTC) == btc("0")


@pytest.mark.characterization
@pytest.mark.integration
def test_short_option_margin_is_a_rate_of_the_premium() -> None:
    rated = option(margins=(Decimal("0.15"), Decimal("0.075")))

    engine, _ = run_orders(DATA, {2: SELL}, Market(instruments=(rated,)))

    account = engine.cache.account_for_venue(VENUE)
    assert account is not None
    # 1 contract x 0.05 BTC x the 7.5 % maintenance rate, at leverage 1;
    # Deribit reserves about 15 % of the underlying, near 0.15 BTC
    assert account.balance_locked(BTC) == btc("0.00375")
