from decimal import Decimal

import pytest

from sbt2.strategies.options.sizing import (
    contract_quantity,
    kelly_fraction,
    proportions,
    shared_fractions,
)


@pytest.mark.unit
def test_kelly_fraction_follows_equation_8_1() -> None:
    fraction = kelly_fraction(risk_free=0.03, dte=45, pop=0.79)

    assert fraction == pytest.approx(0.0139, abs=5e-5)


@pytest.mark.unit
def test_correlated_underlyings_share_the_larger_fraction() -> None:
    correlation = [[1.0, 0.9, 0.1], [0.9, 1.0, 0.1], [0.1, 0.1, 1.0]]

    shared = shared_fractions([0.01, 0.02, 0.005], correlation, threshold=0.7)

    assert shared == [0.02, 0.02, 0.005]


@pytest.mark.unit
def test_fractions_scale_to_proportions_that_sum_to_one() -> None:
    shares = proportions([0.0139, 0.0086])

    assert sum(shares) == pytest.approx(1.0)
    assert shares[0] / shares[1] == pytest.approx(0.0139 / 0.0086)


@pytest.mark.unit
def test_the_quantity_rounds_down_to_the_size_step_and_may_be_zero() -> None:
    step = Decimal("0.1")

    assert contract_quantity(Decimal("0.55"), Decimal("0.2"), step) == Decimal("2.7")
    assert contract_quantity(Decimal("0.01"), Decimal("0.2"), step) == Decimal(0)
