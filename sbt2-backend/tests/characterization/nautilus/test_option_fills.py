import pytest
from nautilus_trader.model import OrderSide, Price, Quantity
from option_kit import CALL_ID, Fill, Market, quote, run_orders, trade


@pytest.mark.characterization
@pytest.mark.integration
def test_a_market_order_fills_at_the_last_trade_however_old() -> None:
    data = [trade(0, "0.0500"), trade(5, "0.0600")]

    _, record = run_orders(data, {2: (OrderSide.BUY, "1.0")})

    assert record.fills == [
        Fill(2.0, OrderSide.BUY, Price.from_str("0.0500"), Quantity.from_str("1.0"))
    ]


@pytest.mark.characterization
@pytest.mark.integration
def test_the_rest_of_an_order_above_the_last_trade_size_fills_a_tick_worse() -> None:
    data = [trade(0, "0.0500"), trade(5, "0.0600")]

    _, record = run_orders(data, {2: (OrderSide.BUY, "7.0")})

    assert [(fill.price, fill.quantity) for fill in record.fills] == [
        (Price.from_str("0.0500"), Quantity.from_str("1.0")),
        (Price.from_str("0.0501"), Quantity.from_str("6.0")),
    ]


@pytest.mark.characterization
@pytest.mark.integration
def test_with_quotes_only_a_market_buy_fills_at_the_ask() -> None:
    data = [
        quote(CALL_ID, 0, ("0.0490", "0.0510")),
        quote(CALL_ID, 3, ("0.0590", "0.0610")),
    ]

    _, record = run_orders(data, {2: (OrderSide.BUY, "1.0")})

    assert [fill.price for fill in record.fills] == [Price.from_str("0.0510")]


@pytest.mark.characterization
@pytest.mark.integration
@pytest.mark.parametrize(
    "market", [Market(), Market(trade_execution=False)], ids=["trades on", "trades off"]
)
def test_a_trade_after_a_quote_sets_the_fill_price(market: Market) -> None:
    data = [
        quote(CALL_ID, 0, ("0.0490", "0.0510")),
        trade(1, "0.0700"),
        quote(CALL_ID, 3, ("0.0590", "0.0610")),
    ]

    _, record = run_orders(data, {2: (OrderSide.BUY, "1.0")}, market)

    assert [fill.price for fill in record.fills] == [Price.from_str("0.0700")]
