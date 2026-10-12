from datetime import UTC, datetime, timedelta

import pytest
from chain_kit import chain_of, clock, ns

from sbt2.core.strategy import IV_LOOKBACK, CachedChain, ChainRecords, NoMarketError

NOW = datetime(2024, 6, 1, tzinfo=UTC)
HOUR = timedelta(hours=1)
RECENT = [40.0, 60.0, 50.0, 80.0, 55.0, 65.0]


def hear(records: ChainRecords, values: list[float]) -> None:
    """Feed ``values`` one per hour, the last one at now."""
    for place, value in enumerate(values):
        records.hear_volatility(ns(NOW - HOUR * (len(values) - 1 - place)), value)


def chain_with(values: list[float]) -> CachedChain:
    records = ChainRecords(clock(NOW))
    hear(records, values)
    return chain_of(records)


@pytest.mark.unit
def test_iv_rank_is_the_place_of_dvol_between_its_look_back_low_and_high() -> None:
    # by hand: (65 - 40) / (80 - 40)
    assert chain_with(RECENT).iv_rank() == pytest.approx(0.625)


@pytest.mark.unit
def test_iv_rank_is_1_at_the_look_back_high_and_0_at_its_low() -> None:
    assert chain_with([40.0, 60.0, 80.0]).iv_rank() == 1.0
    assert chain_with([80.0, 60.0, 40.0]).iv_rank() == 0.0


@pytest.mark.unit
def test_iv_percentile_is_the_share_of_look_back_dvol_below_now() -> None:
    # 40, 60, 50 and 55 of the 6 values are below 65
    assert chain_with(RECENT).iv_percentile() == pytest.approx(4 / 6)


@pytest.mark.unit
def test_the_look_back_defaults_to_365_days() -> None:
    records = ChainRecords(clock(NOW))
    records.hear_volatility(ns(NOW - timedelta(days=366)), 10.0)
    records.hear_volatility(ns(NOW - timedelta(days=365)), 30.0)
    hear(records, [50.0, 40.0])
    chain = chain_of(records)

    assert timedelta(days=365) == IV_LOOKBACK
    assert chain.iv_rank() == pytest.approx(0.5)
    assert chain.iv_percentile() == pytest.approx(1 / 3)


@pytest.mark.unit
def test_a_longer_look_back_reaches_further() -> None:
    records = ChainRecords(clock(NOW))
    records.hear_volatility(ns(NOW - timedelta(days=366)), 10.0)
    hear(records, [50.0, 40.0])

    chain = chain_of(records)

    assert chain.iv_rank(timedelta(days=400)) == pytest.approx(0.75)
    assert chain.iv_percentile(timedelta(days=400)) == pytest.approx(1 / 3)


@pytest.mark.unit
def test_a_shorter_look_back_keeps_only_the_latest_dvol() -> None:
    chain = chain_with(RECENT)

    # 80, 55 and 65 are the values of the last 2 hours
    assert chain.iv_rank(2 * HOUR) == pytest.approx(0.4)
    assert chain.iv_percentile(2 * HOUR) == pytest.approx(1 / 3)


@pytest.mark.unit
def test_the_iv_rank_never_looks_ahead() -> None:
    records = ChainRecords(clock(NOW))
    hear(records, RECENT)
    chain = chain_of(records)
    records.hear_volatility(ns(NOW) + 1, 200.0)

    assert chain.iv_rank() == pytest.approx(0.625)
    assert chain.iv_percentile() == pytest.approx(4 / 6)


@pytest.mark.unit
def test_iv_rank_without_dvol_is_refused() -> None:
    with pytest.raises(NoMarketError, match="0 DVOL values"):
        chain_with([]).iv_rank()


@pytest.mark.unit
def test_iv_rank_and_percentile_need_two_dvol_values() -> None:
    with pytest.raises(NoMarketError, match="1 DVOL values"):
        chain_with([50.0]).iv_percentile()
    with pytest.raises(NoMarketError, match="1 DVOL values"):
        chain_with([50.0]).iv_rank()


@pytest.mark.unit
def test_iv_rank_of_a_flat_dvol_is_refused() -> None:
    with pytest.raises(NoMarketError, match="did not move"):
        chain_with([50.0, 50.0, 50.0]).iv_rank()
