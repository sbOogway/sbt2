import pytest
from kit import (
    FUNDING_INTERVAL,
    HOUR,
    START,
    USDT,
    VENUE,
    funding,
    funding_payments,
    mark,
    quote,
    run_long_one_btc,
    usdt,
)

pytestmark = pytest.mark.characterization

FIRST_FUNDING = START + FUNDING_INTERVAL


def test_venue_charges_funding_as_rate_times_mark_notional() -> None:
    fundings = [funding(START + k * FUNDING_INTERVAL) for k in (1, 2, 3)]
    end = quote(START + 4 * FUNDING_INTERVAL)
    engine = run_long_one_btc([quote(START), mark(START), *fundings, end])

    assert funding_payments(engine) == [usdt("-5.00")] * 3
    account = engine.cache.account_for_venue(VENUE)
    assert account is not None
    assert account.balance_total(USDT) == usdt("9985.00")


def test_funding_notional_uses_mark_price_not_quotes() -> None:
    data = [
        quote(START),
        mark(START, "40000.0"),
        funding(FIRST_FUNDING),
        quote(FIRST_FUNDING + HOUR),
    ]

    assert funding_payments(run_long_one_btc(data)) == [usdt("-4.00")]


def test_funding_without_interval_never_settles() -> None:
    data = [
        quote(START),
        mark(START),
        funding(FIRST_FUNDING, None),
        quote(FIRST_FUNDING + HOUR),
    ]

    assert funding_payments(run_long_one_btc(data)) == []


@pytest.mark.parametrize("offset", [-4 * HOUR, 1])
def test_funding_off_an_epoch_aligned_interval_boundary_never_settles(
    offset: int,
) -> None:
    ts = FIRST_FUNDING + offset
    data = [quote(START), mark(START), funding(ts), quote(FIRST_FUNDING + HOUR)]

    assert funding_payments(run_long_one_btc(data)) == []


def test_position_opened_at_funding_timestamp_pays_that_funding() -> None:
    data = [
        mark(START),
        funding(FIRST_FUNDING),
        quote(FIRST_FUNDING),
        quote(FIRST_FUNDING + HOUR),
    ]

    assert funding_payments(run_long_one_btc(data)) == [usdt("-5.00")]


def test_position_opened_after_funding_timestamp_does_not_pay_it() -> None:
    opened = quote(FIRST_FUNDING + 1)
    data = [mark(START), funding(FIRST_FUNDING), opened, quote(FIRST_FUNDING + HOUR)]

    assert funding_payments(run_long_one_btc(data)) == []
