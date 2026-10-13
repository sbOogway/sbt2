from decimal import Decimal

import pytest
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    CryptoOption,
    Currency,
    InstrumentId,
    OptionKind,
    Price,
    Quantity,
    Symbol,
)
from option_catalog import START, Terms, listed_option

from sbt2.core.strategy import (
    BookState,
    ComboProposal,
    Holding,
    ShortPremiumRules,
    beta_weighted_delta,
)

RULES = ShortPremiumRules()
BTC_PUT = listed_option(
    InstrumentId.from_str("BTC-12JAN24-40000-P.DERIBIT"),
    Terms(OptionKind.PUT, START.replace(day=12), "40000"),
)
BTC_INDEX = InstrumentId.from_str("BTC_USD.DERIBIT")
ETH_INDEX = InstrumentId.from_str("ETH_USD.DERIBIT")


def book(
    *,
    bpr: str = "0",
    defined_bpr: str = "0",
    rank: float | None = 0.0,
) -> BookState:
    return BookState(Decimal(100), rank, Decimal(bpr), Decimal(defined_bpr))


def combo(bpr: str, *, defined: bool = False) -> ComboProposal:
    return ComboProposal(Decimal(bpr), defined)


@pytest.mark.unit
def test_the_allocation_is_linear_in_the_iv_rank() -> None:
    assert RULES.allocation_at(0.0) == Decimal("0.25")
    assert RULES.allocation_at(1.0) == Decimal("0.5")
    assert RULES.allocation_at(0.5) == Decimal("0.375")


@pytest.mark.unit
def test_without_an_iv_rank_the_allocation_is_its_low_end() -> None:
    assert RULES.allocation_at(None) == Decimal("0.25")


@pytest.mark.unit
def test_an_undefined_risk_combo_over_its_cap_is_refused_with_a_reason() -> None:
    reason = RULES.refusal(book(), combo("7.5"))

    assert reason is not None
    assert reason.startswith("undefined_cap")
    assert "BPR 7.5 is above 7.00" in reason


@pytest.mark.unit
def test_a_defined_risk_combo_over_its_cap_is_refused() -> None:
    reason = RULES.refusal(book(), combo("5.5", defined=True))

    assert reason is not None
    assert reason.startswith("defined_cap")
    assert "BPR 5.5 is above 5.00" in reason
    assert RULES.refusal(book(), combo("5.5")) is None


@pytest.mark.unit
def test_a_combo_that_takes_the_bpr_over_the_allocation_is_refused() -> None:
    reason = RULES.refusal(book(bpr="20"), combo("6"))

    assert reason is not None
    assert reason.startswith("allocation")
    assert "would be 26, above 25.00" in reason


@pytest.mark.unit
def test_defined_risk_over_its_share_of_the_allocation_is_refused() -> None:
    reason = RULES.refusal(
        book(bpr="12", defined_bpr="10", rank=1.0), combo("4", defined=True)
    )

    assert reason is not None
    assert reason.startswith("defined_share")
    assert "would be 14, above 12.5" in reason


@pytest.mark.unit
def test_a_combo_within_every_rule_passes() -> None:
    assert RULES.refusal(book(), combo("7")) is None
    assert RULES.refusal(book(bpr="18"), combo("7")) is None
    assert (
        RULES.refusal(book(bpr="10", defined_bpr="5"), combo("1", defined=True)) is None
    )


def eth_put() -> CryptoOption:
    eth = Currency.from_str("ETH")
    return CryptoOption(
        InstrumentId.from_str("ETH-12JAN24-2000-P.DERIBIT"),
        Symbol("ETH-12JAN24-2000-P"),
        eth,
        eth,
        eth,
        True,
        OptionKind.PUT,
        Price.from_str("2000"),
        0,
        dt_to_unix_nanos(START.replace(day=12)),
        4,
        1,
        Price.from_str("0.0001"),
        Quantity.from_str("0.1"),
        0,
        0,
        multiplier=Quantity.from_str("1"),
        margin_init=Decimal(0),
        margin_maint=Decimal(0),
    )


@pytest.mark.unit
def test_beta_weighted_delta_converts_other_underlyings_by_index_price() -> None:
    holdings = [
        Holding(BTC_PUT, Decimal(-2), -0.25),
        Holding(eth_put(), Decimal(-10), -0.5),
    ]
    indexes = {BTC_INDEX: 40000.0, ETH_INDEX: 2000.0}

    found = beta_weighted_delta(holdings, indexes)

    assert found == pytest.approx(0.5 + 0.25)
