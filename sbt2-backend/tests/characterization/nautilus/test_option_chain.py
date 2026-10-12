from typing import Any, override

import pytest
from nautilus_trader.common import GreeksCalculator
from nautilus_trader.model import (
    GreeksData,
    OptionChainSlice,
    OptionGreeks,
    OptionSeriesId,
    QuoteTick,
    StrikeRange,
)
from nautilus_trader.trading import Strategy
from option_kit import (
    CALL_ID,
    EXPIRY,
    PUT_ID,
    STRIKE,
    Market,
    at,
    greeks,
    option,
    quote,
    run_engine,
    trade,
)

SERIES = OptionSeriesId("DERIBIT", "BTC", "BTC", EXPIRY)
BOTH = Market(instruments=(option(CALL_ID), option(PUT_ID)))
HOURLY_MS = 3_600_000


class ChainWatcher(Strategy):
    def __init__(self) -> None:
        super().__init__()
        self.greeks: list[OptionGreeks] = []
        self.slices: list[OptionChainSlice] = []

    def on_start(self) -> None:
        self.subscribe_option_greeks(CALL_ID)
        self.subscribe_option_chain(SERIES, StrikeRange.fixed([STRIKE]), HOURLY_MS)

    @override
    def on_option_greeks(self, greeks: OptionGreeks) -> None:
        self.greeks.append(greeks)

    @override
    def on_option_chain(self, slice: OptionChainSlice) -> None:
        self.slices.append(slice)


class GreeksAsker(Strategy):
    def __init__(self) -> None:
        super().__init__()
        self.answers: list[GreeksData | None] = []

    def on_start(self) -> None:
        self.calculator = GreeksCalculator(self.cache, self.clock)
        self.subscribe_quotes(CALL_ID)

    @override
    def on_quote(self, quote: QuoteTick) -> None:
        self.answers.append(
            self.calculator.instrument_greeks(CALL_ID, flat_interest_rate=0.0)
        )


def watch(data: list[Any]) -> ChainWatcher:
    watcher = ChainWatcher()
    run_engine(data, watcher, BOTH)
    return watcher


@pytest.mark.characterization
@pytest.mark.integration
def test_option_greeks_reach_a_subscribed_strategy() -> None:
    watcher = watch(
        [trade(0, "0.0500"), greeks(CALL_ID, 1, 0.55), greeks(PUT_ID, 1, 0.6)]
    )

    assert [(each.instrument_id, each.mark_iv) for each in watcher.greeks] == [
        (CALL_ID, 0.55)
    ]


@pytest.mark.characterization
@pytest.mark.integration
def test_an_option_chain_slice_needs_quotes() -> None:
    from_trades = watch(
        [trade(0, "0.0500"), greeks(CALL_ID, 1, 0.55), trade(3, "0.0600")]
    )
    from_quotes = watch(
        [
            quote(CALL_ID, 0, ("0.0490", "0.0510")),
            greeks(CALL_ID, 1, 0.55),
            quote(CALL_ID, 3, ("0.0590", "0.0610")),
        ]
    )

    assert from_trades.slices == []
    last = from_quotes.slices[-1]
    call_quote, call_greeks = last.get_call_quote(STRIKE), last.get_call_greeks(STRIKE)
    assert call_quote is not None
    assert call_quote.ts_event == at(3)
    assert call_greeks is not None
    assert call_greeks.mark_iv == 0.55


@pytest.mark.characterization
@pytest.mark.integration
def test_the_greeks_calculator_gives_nothing_without_an_underlying_price() -> None:
    asker = GreeksAsker()
    data = [quote(CALL_ID, 0, ("0.0490", "0.0510")), greeks(CALL_ID, 1, 0.55)]

    run_engine([*data, quote(CALL_ID, 2, ("0.0490", "0.0510"))], asker, BOTH)

    assert asker.answers == [None, None]
