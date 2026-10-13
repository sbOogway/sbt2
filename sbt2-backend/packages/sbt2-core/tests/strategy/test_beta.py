from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from chain_kit import clock, ns

from sbt2.core.strategy import ChainRecords
from sbt2.core.strategy.beta import betas

NOW = datetime(2024, 6, 1, tzinfo=UTC)
DAY = timedelta(days=1)
LOOK_BACK = timedelta(days=30)
BTC_CLOSES = [40_000.0, 41_000.0, 40_500.0, 42_000.0, 41_500.0, 43_000.0]
ETH_CLOSES = [2_000.0, 2_070.0, 2_035.0, 2_160.0, 2_090.0, 2_240.0]


def records_of(closes: list[float]) -> ChainRecords:
    """A chain that heard one index price a day at midnight, the last at now."""
    records = ChainRecords(clock(NOW))
    for place, close in enumerate(closes):
        records.hear_index(ns(NOW - DAY * (len(closes) - 1 - place)), close)
    return records


def returns_of(closes: list[float]) -> np.ndarray:
    return np.diff(closes) / np.array(closes[:-1])


@pytest.mark.unit
def test_beta_is_the_regression_of_daily_index_returns_on_btc() -> None:
    found = betas(
        {"BTC": records_of(BTC_CLOSES), "ETH": records_of(ETH_CLOSES)}, LOOK_BACK
    )

    on_btc, own = returns_of(BTC_CLOSES), returns_of(ETH_CLOSES)
    expected = np.cov(own, on_btc)[0, 1] / np.var(on_btc, ddof=1)
    assert found["ETH"] == pytest.approx(expected)
    assert found["ETH"] != pytest.approx(1.0)


@pytest.mark.unit
def test_beta_is_twice_for_an_underlying_that_moves_twice_as_much() -> None:
    btc = [100.0, 102.0, 99.96, 104.958, 101.80926, 103.0]
    eth = [10.0]
    for each in returns_of(btc):
        eth.append(eth[-1] * (1 + 2 * each))

    found = betas({"BTC": records_of(btc), "ETH": records_of(eth)}, LOOK_BACK)

    assert found["ETH"] == pytest.approx(2.0)


@pytest.mark.unit
def test_beta_is_one_for_btc_and_without_enough_history() -> None:
    short = betas(
        {"BTC": records_of(BTC_CLOSES[-3:]), "ETH": records_of(ETH_CLOSES[-3:])},
        LOOK_BACK,
    )
    flat = betas(
        {"BTC": records_of([1.0] * 6), "ETH": records_of(ETH_CLOSES)}, LOOK_BACK
    )
    no_btc = betas({"ETH": records_of(ETH_CLOSES)}, LOOK_BACK)
    full = betas(
        {"BTC": records_of(BTC_CLOSES), "ETH": records_of(ETH_CLOSES)}, LOOK_BACK
    )

    assert full["BTC"] == 1.0
    assert short["ETH"] == 1.0
    assert flat["ETH"] == 1.0
    assert no_btc["ETH"] == 1.0


@pytest.mark.unit
def test_beta_looks_only_over_the_look_back() -> None:
    older = [30_000.0, 35_000.0, 28_000.0, 36_000.0]
    wild = [3_000.0, 2_000.0, 3_500.0, 1_500.0]
    btc = records_of([*older, *BTC_CLOSES])
    eth = records_of([*wild, *ETH_CLOSES])
    kept = timedelta(days=len(BTC_CLOSES) - 1)

    found = betas({"BTC": btc, "ETH": eth}, kept)
    alone = betas({"BTC": records_of(BTC_CLOSES), "ETH": records_of(ETH_CLOSES)}, kept)

    assert found["ETH"] == pytest.approx(alone["ETH"])
