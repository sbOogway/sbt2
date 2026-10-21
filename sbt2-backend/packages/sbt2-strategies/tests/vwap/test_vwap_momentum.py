import pytest
from bar_engine import BTC, EQUITY
from nautilus_trader.model import OrderSide
from vwap_kit import DAY, day, orders_sent, run_candles, vwap_config

from sbt2.strategies.vwap.momentum import NoiseBand, VwapMomentum, volatility_weight

BUY, SELL = OrderSide.BUY, OrderSide.SELL
OPEN = 100.0


def momentum(**params: float) -> VwapMomentum:
    return VwapMomentum(vwap_config({"days": 2, **params}))


def calm_days(returns: tuple[float, float] = (0.01, 0.01)) -> list[float]:
    """Two sessions that open at 100 and stay at their close all day, so every
    noise band is the mean of the two returns around the open."""
    return [
        price
        for each in returns
        for price in day((1, OPEN), (DAY - 1, OPEN * (1 + each)))
    ]


def trading(*segments: tuple[int, float]) -> list[float]:
    """A third session that opens at 100; the bands are 99 and 101."""
    return day((1, OPEN), *segments)


@pytest.mark.unit
def test_noise_band_is_the_mean_absolute_move_from_the_open_at_that_time_of_day() -> (
    None
):
    band = NoiseBand(days=2)
    assert band.sigma(30) is None

    band.record(30, 0.01)
    band.record(30, 0.03)
    band.record(60, 0.05)

    assert band.sigma(30) == pytest.approx(0.02)
    assert band.sigma(60) is None
    band.record(30, 0.05)
    assert band.sigma(30) == pytest.approx(0.04)


@pytest.mark.integration
def test_goes_long_when_the_close_is_above_the_upper_band_at_a_decision_time() -> None:
    prices = [*calm_days(), *trading((59, OPEN), (1380, 104.0))]

    engine = run_candles(momentum(), prices)

    assert orders_sent(engine) == [(BUY, 2 * DAY + 90), (SELL, 3 * DAY)]


@pytest.mark.integration
def test_goes_short_when_the_close_is_below_the_lower_band_at_a_decision_time() -> None:
    prices = [*calm_days(), *trading((59, OPEN), (1380, 96.0))]

    engine = run_candles(momentum(), prices)

    assert orders_sent(engine) == [(SELL, 2 * DAY + 90), (BUY, 3 * DAY)]


@pytest.mark.integration
def test_decides_only_every_30_minutes() -> None:
    prices = [*calm_days(), *trading((60, OPEN), (1379, 104.0))][: 2 * DAY + 100]

    engine = run_candles(momentum(), prices)

    assert orders_sent(engine) == [(BUY, 2 * DAY + 90)]


@pytest.mark.integration
def test_long_stops_out_below_the_higher_of_the_upper_band_and_the_vwap() -> None:
    prices = [*calm_days(), *trading((29, OPEN), (150, 108.0), (30, 103.0))]

    engine = run_candles(momentum(), prices[: 2 * DAY + 240])

    assert orders_sent(engine) == [(BUY, 2 * DAY + 60), (SELL, 2 * DAY + 210)]


@pytest.mark.integration
def test_is_flat_at_the_session_end() -> None:
    prices = [*calm_days(), *trading((59, OPEN), (1380, 104.0)), 104.0, 104.0]

    engine = run_candles(momentum(), prices)

    assert engine.portfolio.net_position(BTC) == 0


@pytest.mark.unit
@pytest.mark.parametrize(
    ("cap", "weight"), [(4.0, 0.02 / 0.014142135623730951), (1.0, 1.0)]
)
def test_size_targets_the_daily_volatility_capped_at_the_leverage(
    cap: float, weight: float
) -> None:
    assert volatility_weight([0.01, 0.03], 0.02, cap) == pytest.approx(weight)


@pytest.mark.unit
def test_size_is_the_cap_without_volatility() -> None:
    assert volatility_weight([0.01, 0.01], 0.02, 3.0) == 3.0


@pytest.mark.integration
def test_the_position_is_the_weight_times_the_equity() -> None:
    prices = [*calm_days(), *trading((59, OPEN), (1380, 104.0))]

    engine = run_candles(momentum(max_leverage=3.0), prices[: 2 * DAY + 100])

    [position] = engine.cache.positions()
    assert float(position.quantity) * 104.0 == pytest.approx(
        3 * EQUITY.as_double(), rel=1e-3
    )
