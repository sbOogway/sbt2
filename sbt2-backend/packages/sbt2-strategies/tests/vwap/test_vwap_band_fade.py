import pytest
from nautilus_trader.model import OrderSide
from vwap_kit import DAY, orders_sent, run_candles, vwap_config

from sbt2.strategies.vwap.band_fade import VwapBandFade

BUY, SELL = OrderSide.BUY, OrderSide.SELL
NOISE = 148
ENTRY, EXIT = 150, 180


def fade() -> VwapBandFade:
    return VwapBandFade(vwap_config({}))


def noise() -> list[float]:
    """Two hours and a half minus two minutes around 100, the VWAP's 1 sd."""
    return [99.0 if minute % 2 == 0 else 101.0 for minute in range(NOISE)]


def spiking(price: float, *then: float) -> list[float]:
    """The noise, two minutes at ``price`` that end at the first decision, then
    ``then`` per minute until the second."""
    return [*noise(), price, price, *then]


@pytest.mark.integration
def test_shorts_when_the_close_crosses_above_the_upper_band() -> None:
    engine = run_candles(fade(), spiking(110.0, 110.0))

    assert orders_sent(engine) == [(SELL, ENTRY)]


@pytest.mark.integration
def test_longs_when_the_close_crosses_below_the_lower_band() -> None:
    engine = run_candles(fade(), spiking(90.0, 90.0))

    assert orders_sent(engine) == [(BUY, ENTRY)]


@pytest.mark.integration
def test_exits_at_the_vwap() -> None:
    engine = run_candles(fade(), spiking(110.0, *[100.0] * 30))

    assert orders_sent(engine) == [(SELL, ENTRY), (BUY, EXIT)]


@pytest.mark.integration
def test_exits_at_the_stop_band() -> None:
    prices = spiking(110.0, *[110.0] * 28, 130.0, 130.0)

    engine = run_candles(fade(), prices)

    assert orders_sent(engine) == [(SELL, ENTRY), (BUY, EXIT)]


@pytest.mark.integration
def test_is_flat_at_the_session_end() -> None:
    late = [99.0 if minute % 2 == 0 else 101.0 for minute in range(DAY - 32)]
    prices = [*late, 110.0, 110.0, *[110.0] * 30]

    engine = run_candles(fade(), prices)

    assert orders_sent(engine) == [(SELL, DAY - 30), (BUY, DAY)]
