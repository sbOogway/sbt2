from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    Bar,
    CryptoPerpetual,
    Currency,
    InstrumentId,
    Price,
    Quantity,
    Symbol,
)

from sbt2.core.strategy import Anchor, MultiVenueVwap
from sbt2.data import candle_type

MONDAY = datetime(2024, 1, 1, tzinfo=UTC)
MINUTE = timedelta(minutes=1)
_MINUTE_NS = 60_000_000_000


def perpetual(
    code: str, multiplier: str = "1", *, inverse: bool = False
) -> CryptoPerpetual:
    return CryptoPerpetual(
        InstrumentId.from_str(code),
        Symbol(code.partition(".")[0]),
        Currency.from_str("BTC"),
        Currency.from_str("USD" if inverse else "USDT"),
        Currency.from_str("BTC" if inverse else "USDT"),
        inverse,
        1,
        3,
        Price.from_str("0.1"),
        Quantity.from_str("0.001"),
        0,
        0,
        multiplier=Quantity.from_str(multiplier),
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
    )


FIRST = perpetual("BTCUSDT-PERP.BINANCE")
SECOND = perpetual("BTC-USDT-SWAP.OKX", multiplier="0.01")
INVERSE = perpetual("BTC-PERPETUAL.DERIBIT", inverse=True)


def bar(
    instrument: CryptoPerpetual,
    minute: datetime,
    typical: float,
    volume: float,
) -> Bar:
    """A candle of the minute that opens at ``minute`` whose high, low and close
    average ``typical``, stamped 1 ns before its close, as the catalog holds it."""
    ts = dt_to_unix_nanos(minute) + _MINUTE_NS - 1
    return Bar(
        candle_type(instrument.id),
        Price(typical, 1),
        Price(typical + 2, 1),
        Price(typical - 2, 1),
        Price(typical, 1),
        Quantity(volume, 3),
        ts,
        ts,
    )


def feed(vwap: MultiVenueVwap, *bars: Bar) -> None:
    for each in bars:
        vwap.update(each)


@pytest.mark.unit
def test_vwap_weights_each_exchanges_typical_price_by_its_volume() -> None:
    other = perpetual("ETHUSDT-PERP.BINANCE")
    vwap = MultiVenueVwap([FIRST, other])

    feed(vwap, bar(FIRST, MONDAY, 100, 3), bar(other, MONDAY, 110, 1))

    assert vwap.vwap == pytest.approx((100 * 3 + 110 * 1) / 4)


@pytest.mark.unit
def test_typical_price_is_the_mean_of_high_low_and_close() -> None:
    vwap = MultiVenueVwap([FIRST])
    skewed = Bar(
        candle_type(FIRST.id),
        Price(100, 1),
        Price(106, 1),
        Price(97, 1),
        Price(103, 1),
        Quantity(1, 3),
        dt_to_unix_nanos(MONDAY) + _MINUTE_NS - 1,
        dt_to_unix_nanos(MONDAY) + _MINUTE_NS - 1,
    )

    feed(vwap, skewed)

    assert vwap.vwap == pytest.approx((106 + 97 + 103) / 3)


@pytest.mark.unit
def test_volume_counts_in_the_base_coin() -> None:
    vwap = MultiVenueVwap([FIRST, SECOND])

    feed(vwap, bar(FIRST, MONDAY, 100, 5), bar(SECOND, MONDAY, 110, 500))

    assert vwap.vwap == pytest.approx((100 * 5 + 110 * 5) / 10)
    assert vwap.shares() == pytest.approx({FIRST.id: 0.5, SECOND.id: 0.5})


@pytest.mark.unit
def test_volume_of_an_inverse_perpetual_counts_in_the_base_coin_at_its_price() -> None:
    vwap = MultiVenueVwap([FIRST, INVERSE])

    feed(vwap, bar(FIRST, MONDAY, 100, 1), bar(INVERSE, MONDAY, 100, 300))

    assert vwap.shares() == pytest.approx({FIRST.id: 0.25, INVERSE.id: 0.75})


@pytest.mark.unit
def test_exchange_without_a_kline_is_left_out_of_that_minute() -> None:
    other = perpetual("ETHUSDT-PERP.BINANCE")
    vwap = MultiVenueVwap([FIRST, other])

    feed(
        vwap,
        bar(FIRST, MONDAY, 100, 3),
        bar(other, MONDAY, 110, 1),
        bar(FIRST, MONDAY + MINUTE, 200, 1),
        bar(FIRST, MONDAY + 2 * MINUTE, 300, 1),
    )

    assert vwap.vwap == pytest.approx((100 * 3 + 110 * 1 + 200 * 1) / 5)
    assert vwap.shares() == pytest.approx({FIRST.id: 0.8, other.id: 0.2})


@pytest.mark.unit
def test_minute_is_published_once_every_feed_reported_or_a_later_minute_starts() -> (
    None
):
    other = perpetual("ETHUSDT-PERP.BINANCE")
    vwap = MultiVenueVwap([FIRST, other])

    feed(vwap, bar(FIRST, MONDAY, 100, 1))
    assert vwap.vwap is None

    feed(vwap, bar(other, MONDAY, 110, 1))
    assert vwap.vwap == pytest.approx(105)

    feed(vwap, bar(FIRST, MONDAY + MINUTE, 200, 2))
    assert vwap.vwap == pytest.approx(105)

    feed(vwap, bar(FIRST, MONDAY + 2 * MINUTE, 300, 1))
    assert vwap.vwap == pytest.approx((100 + 110 + 400) / 4)


@pytest.mark.unit
def test_session_anchor_resets_at_midnight_utc() -> None:
    vwap = MultiVenueVwap([FIRST], Anchor.SESSION)
    evening = MONDAY + timedelta(hours=23, minutes=59)

    feed(vwap, bar(FIRST, MONDAY, 50, 1), bar(FIRST, evening, 100, 1))
    assert vwap.vwap == pytest.approx(75)

    feed(vwap, bar(FIRST, evening + MINUTE, 200, 1))
    assert vwap.vwap == pytest.approx(200)

    feed(vwap, bar(FIRST, evening + 2 * MINUTE, 300, 1))
    assert vwap.vwap == pytest.approx(250)


@pytest.mark.unit
def test_week_anchor_resets_on_monday_midnight_utc() -> None:
    vwap = MultiVenueVwap([FIRST], Anchor.WEEK)
    saturday_night = MONDAY + timedelta(days=5, hours=23, minutes=59)
    sunday_night = MONDAY + timedelta(days=6, hours=23, minutes=59)

    feed(vwap, bar(FIRST, MONDAY, 50, 1), bar(FIRST, saturday_night, 100, 1))
    feed(vwap, bar(FIRST, saturday_night + MINUTE, 200, 1))
    feed(vwap, bar(FIRST, sunday_night, 400, 1))
    assert vwap.vwap == pytest.approx((50 + 100 + 200 + 400) / 4)

    feed(vwap, bar(FIRST, sunday_night + MINUTE, 600, 1))
    assert vwap.vwap == pytest.approx(600)


@pytest.mark.unit
def test_strategy_anchor_resets_when_the_strategy_calls_it() -> None:
    vwap = MultiVenueVwap([FIRST], Anchor.STRATEGY)
    evening = MONDAY + timedelta(hours=23, minutes=59)

    feed(vwap, bar(FIRST, evening, 100, 1), bar(FIRST, evening + MINUTE, 200, 1))
    assert vwap.vwap == pytest.approx(150)

    vwap.reset()
    assert vwap.vwap is None
    feed(vwap, bar(FIRST, evening + 2 * MINUTE, 400, 1))
    feed(vwap, bar(FIRST, evening + 3 * MINUTE, 500, 1))
    assert vwap.vwap == pytest.approx(450)


@pytest.mark.unit
def test_bands_lie_n_volume_weighted_standard_deviations_around_the_vwap() -> None:
    vwap = MultiVenueVwap([FIRST])

    feed(vwap, bar(FIRST, MONDAY, 100, 1), bar(FIRST, MONDAY + MINUTE, 110, 1))

    assert vwap.vwap == pytest.approx(105)
    assert vwap.bands(2) == pytest.approx((95, 115))

    feed(vwap, bar(FIRST, MONDAY + 2 * MINUTE, 110, 1))
    feed(vwap, bar(FIRST, MONDAY + 3 * MINUTE, 110, 2))
    weighted = [(100, 1), (110, 1), (110, 1), (110, 2)]
    mean = sum(price * volume for price, volume in weighted) / 5
    variance = sum(volume * (price - mean) ** 2 for price, volume in weighted) / 5
    spread = 1.5 * variance**0.5
    assert vwap.bands(1.5) == pytest.approx((mean - spread, mean + spread))


@pytest.mark.unit
def test_shares_give_each_exchange_volume_since_the_anchor() -> None:
    other = perpetual("ETHUSDT-PERP.BINANCE")
    vwap = MultiVenueVwap([FIRST, other], Anchor.STRATEGY)

    feed(vwap, bar(FIRST, MONDAY, 100, 1), bar(other, MONDAY, 100, 1))
    vwap.reset()
    feed(vwap, bar(FIRST, MONDAY + MINUTE, 100, 1), bar(other, MONDAY + MINUTE, 100, 3))

    assert vwap.shares() == pytest.approx({FIRST.id: 0.25, other.id: 0.75})


@pytest.mark.unit
def test_vwap_is_not_ready_before_the_first_minute() -> None:
    vwap = MultiVenueVwap([FIRST, SECOND])

    assert vwap.vwap is None
    assert vwap.bands(2) is None
    assert vwap.shares() == {}
