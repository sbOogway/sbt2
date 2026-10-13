from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

from sbt2.core.market import NoRateError, Rates

NOON = datetime(2024, 1, 1, 12, tzinfo=UTC)
HOUR = timedelta(hours=1)


def prices(*values: float) -> pd.Series:
    """One price an hour from noon."""
    index = pd.DatetimeIndex([NOON + HOUR * k for k in range(len(values))])
    return pd.Series(values, index=index)


def at(*hours: int) -> pd.DatetimeIndex:
    return pd.DatetimeIndex([NOON + HOUR * each for each in hours])


RATES = Rates(
    "BTC", {"BTC": prices(40_000.0, 44_000.0), "ETH": prices(2_000.0, 2_200.0)}
)


@pytest.mark.unit
def test_an_amount_in_the_reporting_currency_converts_at_one() -> None:
    assert list(RATES.factors(["BTC", "BTC"], at(0, 1))) == [1.0, 1.0]


@pytest.mark.unit
def test_a_coin_converts_at_its_index_over_the_reporting_one_of_the_time() -> None:
    found = RATES.factors(["ETH", "ETH"], at(0, 1))

    assert list(found) == pytest.approx([2_000.0 / 40_000.0, 2_200.0 / 44_000.0])


@pytest.mark.unit
def test_a_price_holds_until_the_next_one() -> None:
    found = RATES.factors(["ETH", "BTC", "ETH"], at(5, 5, 0))

    assert list(found) == pytest.approx([0.05, 1.0, 0.05])


@pytest.mark.unit
def test_a_coin_without_a_price_yet_cannot_convert() -> None:
    with pytest.raises(NoRateError, match="ETH yet"):
        RATES.factors(["ETH"], pd.DatetimeIndex([NOON - HOUR]))
    with pytest.raises(NoRateError, match="to convert SOL"):
        RATES.factors(["SOL"], at(0))
