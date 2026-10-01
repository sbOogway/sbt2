from decimal import Decimal

import pytest
from nautilus_trader.model import (
    CryptoPerpetual,
    Currency,
    InstrumentId,
    Money,
    OrderSide,
    Price,
    Quantity,
    Symbol,
)
from nautilus_trader.risk import FixedRiskSizer

from sbt2.strategies.bracket_risk import BracketParams, Entry, plan_bracket


def perpetual() -> CryptoPerpetual:
    usdt = Currency.from_str("USDT")
    return CryptoPerpetual(
        InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT"),
        Symbol("BTCUSDT"),
        Currency.from_str("BTC"),
        usdt,
        usdt,
        False,
        1,
        3,
        Price.from_str("0.1"),
        Quantity.from_str("0.001"),
        0,
        0,
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
    )


@pytest.mark.unit
def test_entries_are_sized_with_the_fixed_risk_sizer() -> None:
    instrument = perpetual()
    equity = Money.from_str("10000 USDT")
    params = BracketParams(risk=Decimal("0.01"), stop=Decimal("0.005"))

    bracket = plan_bracket(
        instrument, Entry(OrderSide.BUY, Price.from_str("50000.0"), equity), params
    )

    expected = FixedRiskSizer(instrument).calculate(
        Price.from_str("50000.0"),
        Price.from_str("49750.0"),
        equity,
        Decimal("0.01"),
        unit_batch_size=Decimal("0.001"),
    )
    assert bracket.quantity == expected
    assert expected == Quantity.from_str("0.400")
