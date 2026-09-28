import pytest
from kit import (
    FUNDING_INTERVAL,
    HOUR,
    INSTRUMENT_ID,
    START,
    USDT,
    VENUE,
    funding,
    funding_payments,
    mark,
    quote,
    run_engine,
    run_long_one_btc,
    usdt,
)
from nautilus_trader.model import (
    OrderSide,
    Position,
    PositionAdjustmentType,
    Quantity,
    QuoteTick,
)
from nautilus_trader.trading import Strategy

pytestmark = pytest.mark.characterization

FIRST_FUNDING = START + FUNDING_INTERVAL


def test_venue_charges_funding_as_rate_times_mark_notional() -> None:
    fundings = [funding(START + k * FUNDING_INTERVAL) for k in (1, 2, 3)]
    end = quote(START + 4 * FUNDING_INTERVAL)
    engine = run_long_one_btc([quote(START), mark(START), *fundings, end])

    assert funding_payments(engine.cache) == [usdt("-5.00")] * 3
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

    assert funding_payments(run_long_one_btc(data).cache) == [usdt("-4.00")]


def test_funding_without_interval_never_settles() -> None:
    data = [
        quote(START),
        mark(START),
        funding(FIRST_FUNDING, None),
        quote(FIRST_FUNDING + HOUR),
    ]

    assert funding_payments(run_long_one_btc(data).cache) == []


@pytest.mark.parametrize("offset", [-4 * HOUR, 1])
def test_funding_off_an_epoch_aligned_interval_boundary_never_settles(
    offset: int,
) -> None:
    ts = FIRST_FUNDING + offset
    data = [quote(START), mark(START), funding(ts), quote(FIRST_FUNDING + HOUR)]

    assert funding_payments(run_long_one_btc(data).cache) == []


def test_position_opened_at_funding_timestamp_pays_that_funding() -> None:
    data = [
        mark(START),
        funding(FIRST_FUNDING),
        quote(FIRST_FUNDING),
        quote(FIRST_FUNDING + HOUR),
    ]

    assert funding_payments(run_long_one_btc(data).cache) == [usdt("-5.00")]


def test_position_opened_after_funding_timestamp_does_not_pay_it() -> None:
    opened = quote(FIRST_FUNDING + 1)
    data = [mark(START), funding(FIRST_FUNDING), opened, quote(FIRST_FUNDING + HOUR)]

    assert funding_payments(run_long_one_btc(data).cache) == []


class BuyOneThenReverse(Strategy):
    """Buys 1 BTC on the first quote and sells 2 on the quote at ``reverse_at``."""

    def __init__(self, reverse_at: int) -> None:
        super().__init__()
        self.reverse_at = reverse_at

    def on_start(self) -> None:
        self.subscribe_quotes(INSTRUMENT_ID)
        self.submit(OrderSide.BUY, "1.000")

    def on_quote(self, quote: QuoteTick) -> None:
        if quote.ts_event == self.reverse_at:
            self.submit(OrderSide.SELL, "2.000")

    def submit(self, side: OrderSide, quantity: str) -> None:
        order = self.order_factory.market(
            INSTRUMENT_ID, side, Quantity.from_str(quantity)
        )
        self.submit_order(order)


def fundings_of(position: Position) -> list[object]:
    return [
        adjustment.pnl_change
        for adjustment in position.adjustments()
        if adjustment.adjustment_type == PositionAdjustmentType.FUNDING
    ]


def test_reversing_a_netting_position_moves_its_funding_to_a_snapshot() -> None:
    reverse_at = FIRST_FUNDING + HOUR
    second_funding = START + 2 * FUNDING_INTERVAL
    data = [
        quote(START),
        mark(START),
        funding(FIRST_FUNDING),
        quote(reverse_at),
        funding(second_funding),
        quote(second_funding + HOUR),
    ]
    cache = run_engine(data, BuyOneThenReverse(reverse_at)).cache

    [position] = cache.positions()
    [snapshot] = cache.position_snapshots()
    assert fundings_of(snapshot) == [usdt("-5.00")]
    assert fundings_of(position) == [usdt("5.00")]
