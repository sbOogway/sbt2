import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from nautilus_trader.model import (
    CryptoOption,
    Currency,
    InstrumentId,
    OptionKind,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
)

from sbt2.core.assets import OptionHistory, QuoteSettings, quote_ticks

START = datetime(2024, 1, 1, 10, tzinfo=UTC)
EXPIRY = datetime(2024, 2, 1, 8, tzinfo=UTC)
STRIKE = 50000.0
VOL = 0.6
INDEX = 45000.0
SECONDS_PER_YEAR = 365 * 86_400
BTC = Currency.from_str("BTC")
TICK = "0.0001"


def contract(kind: OptionKind = OptionKind.CALL, tick: str = TICK) -> CryptoOption:
    suffix = "C" if kind == OptionKind.CALL else "P"
    instrument_id = InstrumentId.from_str(f"BTC-1FEB24-50000-{suffix}.DERIBIT")
    return CryptoOption(
        instrument_id,
        Symbol(instrument_id.symbol.value),
        BTC,
        BTC,
        BTC,
        True,
        kind,
        Price.from_str("50000"),
        0,
        int(pd.Timestamp(EXPIRY).value),
        len(tick.split(".")[1]),
        1,
        Price.from_str(tick),
        Quantity.from_str("0.1"),
        0,
        0,
        multiplier=Quantity.from_str("1"),
    )


def call_price(spot: float, vol: float, years: float) -> float:
    """Black-Scholes by hand with no rates, in BTC: the USD price over the spot."""
    d1 = (math.log(spot / STRIKE) + vol * vol * years / 2) / (vol * math.sqrt(years))
    d2 = d1 - vol * math.sqrt(years)
    return (spot * _cdf(d1) - STRIKE * _cdf(d2)) / spot


def put_price(spot: float, vol: float, years: float) -> float:
    """Put-call parity with no rates: the call less the spot, plus the strike."""
    return call_price(spot, vol, years) - 1 + STRIKE / spot


def _cdf(x: float) -> float:
    return (1 + math.erf(x / math.sqrt(2))) / 2


def years_left(at: datetime) -> float:
    return (EXPIRY - at).total_seconds() / SECONDS_PER_YEAR


def series(values: dict[datetime, float]) -> pd.Series:
    return pd.Series(values, dtype=float).rename_axis("ts_event")


def history(
    option: CryptoOption,
    marks: dict[datetime, float],
    index: dict[datetime, float],
) -> OptionHistory:
    """The marks, each with an IV record at its time and the index of that time."""
    underlying = dict.fromkeys(marks, INDEX)
    return OptionHistory(
        option,
        pd.DataFrame({"price": series(marks)}),
        pd.DataFrame(
            {
                "mark_iv": series(dict.fromkeys(marks, 0.3)),
                "underlying_price": series(underlying),
            }
        ),
        series({**underlying, **index}),
    )


def mid(quote: QuoteTick) -> float:
    return (float(quote.bid_price) + float(quote.ask_price)) / 2


def quote_times(quotes: list[QuoteTick]) -> list[datetime]:
    return [datetime.fromtimestamp(each.ts_event / 1e9, UTC) for each in quotes]


def span(minutes: int, start: datetime = START) -> tuple[datetime, datetime]:
    return start, start + timedelta(minutes=minutes)


@pytest.mark.unit
def test_a_quote_at_a_trade_is_centred_on_the_trades_mark() -> None:
    mark = call_price(INDEX, VOL, years_left(START))

    [quote] = quote_ticks(
        history(contract(), {START: mark}, {}), QuoteSettings(), span(1)
    )

    assert mid(quote) == pytest.approx(mark, abs=1e-4)
    assert quote.ts_event == pd.Timestamp(START).value


@pytest.mark.unit
@pytest.mark.parametrize(
    ("kind", "price", "direction"),
    [
        (OptionKind.CALL, call_price, 1),
        (OptionKind.PUT, put_price, -1),
    ],
)
def test_a_quote_between_trades_reprices_the_last_vol_on_the_current_index(
    kind: OptionKind, price: Callable[[float, float, float], float], direction: int
) -> None:
    option = contract(kind)
    mark = price(INDEX, VOL, years_left(START))
    later = START + timedelta(minutes=30)
    moved = INDEX * 1.05

    quotes = quote_ticks(
        history(option, {START: mark}, {later: moved}), QuoteSettings(), span(31)
    )

    at_later = quote_times(quotes).index(later)
    last = quotes[at_later]
    expected = price(moved, VOL, years_left(later))
    assert mid(last) == pytest.approx(expected, abs=1e-4)
    assert (mid(last) - mid(quotes[0])) * direction > 0


@pytest.mark.unit
def test_the_quotes_come_on_the_venues_interval() -> None:
    mark = call_price(INDEX, VOL, years_left(START))
    marked = history(contract(), {START: mark}, {})

    minutely = quote_ticks(marked, QuoteSettings(interval_seconds=60), span(10))
    every_five = quote_ticks(marked, QuoteSettings(interval_seconds=300), span(10))

    assert quote_times(minutely) == [START + timedelta(minutes=m) for m in range(10)]
    assert quote_times(every_five) == [START, START + timedelta(minutes=5)]


@pytest.mark.unit
def test_a_contract_has_no_quote_before_its_first_mark() -> None:
    first = START + timedelta(minutes=5, seconds=30)
    mark = call_price(INDEX, VOL, years_left(first))

    quotes = quote_ticks(
        history(contract(), {first: mark}, {}), QuoteSettings(), span(10)
    )

    assert quote_times(quotes)[0] == START + timedelta(minutes=6)


@pytest.mark.unit
def test_a_contract_has_no_quote_after_its_expiry() -> None:
    mark = call_price(INDEX, VOL, years_left(EXPIRY - timedelta(minutes=5)))
    begin = EXPIRY - timedelta(minutes=5)

    quotes = quote_ticks(
        history(contract(), {begin: mark}, {}), QuoteSettings(), span(10, begin)
    )

    assert quote_times(quotes) == [begin + timedelta(minutes=m) for m in range(5)]
