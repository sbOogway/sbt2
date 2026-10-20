import pytest
from bar_engine import BTC, EQUITY
from nautilus_trader.model import OrderSide
from vwap_kit import DAY, day, orders_sent, run_candles, vwap_config

from sbt2.strategies.vwap_trend import VwapTrend

LONG, SHORT = OrderSide.BUY, OrderSide.SELL


def trend() -> VwapTrend:
    return VwapTrend(vwap_config({}))


def session() -> list[float]:
    """100 for an hour, 110 until 05:00, then 90."""
    return day((60, 100.0), (240, 110.0), (1140, 90.0))


@pytest.mark.integration
def test_long_above_the_session_vwap_and_short_below_at_decision_times() -> None:
    engine = run_candles(trend(), session()[:420])

    assert orders_sent(engine) == [(LONG, 90), (SHORT, 330)]


@pytest.mark.integration
def test_is_flat_at_the_session_end() -> None:
    engine = run_candles(trend(), [*session(), 90.0, 90.0])

    assert orders_sent(engine)[-1] == (LONG, DAY)
    assert engine.portfolio.net_position(BTC) == 0


@pytest.mark.integration
def test_holds_the_whole_equity_without_leverage() -> None:
    engine = run_candles(trend(), session()[:120])

    [position] = engine.cache.positions()
    assert float(position.quantity) * 110.0 == pytest.approx(
        EQUITY.as_double(), rel=1e-3
    )
