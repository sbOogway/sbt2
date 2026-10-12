from decimal import Decimal

import pytest
from nautilus_trader.model import (
    CryptoOption,
    Currency,
    InstrumentId,
    OptionKind,
    Price,
    Quantity,
    Symbol,
)

from sbt2.core.assets import DeliveryFee, settlement_price

BTC = Currency.from_str("BTC")
STRIKE = Decimal(50_000)


def contract(kind: OptionKind) -> CryptoOption:
    suffix = "C" if kind == OptionKind.CALL else "P"
    instrument_id = InstrumentId.from_str(f"BTC-1FEB24-50000-{suffix}.DERIBIT")
    return CryptoOption(
        instrument_id,
        Symbol(instrument_id.symbol.value),
        BTC,
        BTC,
        BTC,
        True,
        kind,
        Price.from_str(str(STRIKE)),
        0,
        1,
        4,
        1,
        Price.from_str("0.0001"),
        Quantity.from_str("0.1"),
        0,
        0,
        multiplier=Quantity.from_str("1"),
    )


@pytest.mark.unit
def test_an_in_the_money_call_settles_at_its_intrinsic_value_in_the_coin() -> None:
    price = settlement_price(contract(OptionKind.CALL), Decimal(55_000))

    assert price == Decimal(5_000) / Decimal(55_000)


@pytest.mark.unit
def test_an_in_the_money_put_settles_at_its_intrinsic_value_in_the_coin() -> None:
    price = settlement_price(contract(OptionKind.PUT), Decimal(40_000))

    assert price == Decimal(10_000) / Decimal(40_000)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "delivery"),
    [(OptionKind.CALL, 45_000), (OptionKind.PUT, 55_000), (OptionKind.CALL, 50_000)],
)
def test_an_out_of_the_money_option_settles_at_zero(
    kind: OptionKind, delivery: int
) -> None:
    assert settlement_price(contract(kind), Decimal(delivery)) == 0


@pytest.mark.unit
def test_the_delivery_fee_is_a_rate_of_the_underlying_capped_at_a_rate_of_the_value() -> (
    None
):
    fee = DeliveryFee(rate=Decimal("0.00015"), cap_rate=Decimal("0.125"))

    assert fee.amount(Decimal(2), Decimal("0.5")) == Decimal("0.0003")
    assert fee.amount(Decimal(2), Decimal("0.001")) == Decimal("0.000125")
    assert fee.amount(Decimal(2), Decimal(0)) == 0
