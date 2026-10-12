from decimal import Decimal

import pytest
from nautilus_trader.model import OptionKind
from option_catalog import option

from sbt2.core.assets import ContractHolding, MarginRates, OptionQuote

INDEX = Decimal(45_000)
MARK = Decimal("0.05")
RATES = MarginRates()


def call(quantity: int) -> ContractHolding:
    return ContractHolding(option(kind=OptionKind.CALL), Decimal(quantity))


def put(quantity: int) -> ContractHolding:
    return ContractHolding(option(kind=OptionKind.PUT), Decimal(quantity))


@pytest.mark.unit
def test_a_long_option_needs_its_premium_only() -> None:
    margin = RATES.initial_margin(call(2), OptionQuote(MARK, INDEX))

    assert margin == 2 * MARK


@pytest.mark.unit
def test_a_short_out_of_the_money_call_needs_the_floor_plus_its_mark() -> None:
    # strike 50,000, index 45,000: 0.15 - 5,000 / 45,000 is below the floor
    margin = RATES.initial_margin(call(-3), OptionQuote(MARK, INDEX))

    assert margin == 3 * (Decimal("0.1") + MARK)


@pytest.mark.unit
def test_a_short_near_the_money_call_needs_fifteen_percent_less_its_otm_amount_plus_its_mark() -> (
    None
):
    index = Decimal(49_000)

    margin = RATES.initial_margin(call(-1), OptionQuote(MARK, index))

    assert margin == Decimal("0.15") - Decimal(1_000) / index + MARK


@pytest.mark.unit
def test_a_short_put_needs_at_least_its_maintenance_margin() -> None:
    rates = MarginRates(floor_rate=Decimal(0), maintenance_rate=Decimal("0.3"))
    quote = OptionQuote(MARK, INDEX)

    margin = rates.initial_margin(put(-1), quote)

    assert margin == rates.maintenance_margin(put(-1), quote)
    assert margin == Decimal("0.3") + MARK


@pytest.mark.unit
def test_the_maintenance_margin_of_a_short_option_is_its_rate_plus_its_mark() -> None:
    margin = RATES.maintenance_margin(call(-2), OptionQuote(MARK, INDEX))

    assert margin == 2 * (Decimal("0.075") + MARK)
