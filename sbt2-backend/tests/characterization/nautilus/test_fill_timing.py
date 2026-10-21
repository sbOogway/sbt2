from typing import Any

import pytest
from kit import INSTRUMENT_ID, START, run_engine
from nautilus_trader.model import (
    AggregationSource,
    AggressorSide,
    Bar,
    BarType,
    OrderSide,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)
from nautilus_trader.trading import Strategy

MINUTE = 60_000_000_000
CANDLES = BarType.from_str(f"{INSTRUMENT_ID}-1-MINUTE-LAST-EXTERNAL")
MINUTES = BarType.from_str(f"{INSTRUMENT_ID}-1-MINUTE-LAST-INTERNAL@1-MINUTE-EXTERNAL")
VOLUME = "100.000"


class BuyOnFirstMinute(Strategy):
    """Sends one market order when the first internal 1-minute bar closes."""

    def __init__(self, quantity: str) -> None:
        super().__init__()
        self.quantity = quantity

    def on_start(self) -> None:
        self.sent = False
        self.subscribe_bars(MINUTES)

    def on_bar(self, bar: Bar) -> None:
        if self.sent or bar.bar_type.aggregation_source != AggregationSource.INTERNAL:
            return
        self.sent = True
        order = self.order_factory.market(
            INSTRUMENT_ID, OrderSide.BUY, Quantity.from_str(self.quantity)
        )
        self.submit_order(order)


def candle(minute: int, prices: tuple[str, str, str, str]) -> Bar:
    """The candle of ``minute``, stamped 1 ns before its close."""
    ts = START + (minute + 1) * MINUTE - 1
    opened, high, low, close = (Price.from_str(each) for each in prices)
    return Bar(CANDLES, opened, high, low, close, Quantity.from_str(VOLUME), ts, ts)


def boundary_trade(price: str) -> TradeTick:
    ts = START + MINUTE
    return TradeTick(
        INSTRUMENT_ID,
        Price.from_str(price),
        Quantity.from_str("25.000"),
        AggressorSide.NO_AGGRESSOR,
        TradeId(str(ts)),
        ts,
        ts,
    )


def fills(data: list[Any], quantity: str) -> list[tuple[str, str, int]]:
    engine = run_engine(data, BuyOnFirstMinute(quantity))
    report = engine.generate_fills_report()
    return [
        (str(qty), str(px), ts.value)
        for qty, px, ts in zip(
            report["last_qty"], report["last_px"], report["ts_event"], strict=True
        )
    ]


SIGNAL = candle(0, ("100.0", "110.0", "90.0", "105.0"))
FOLLOWING = candle(1, ("120.0", "130.0", "115.0", "125.0"))


@pytest.mark.characterization
@pytest.mark.integration
def test_data_at_a_bar_boundary_is_processed_before_the_internal_bar_closes() -> None:
    filled = fills([SIGNAL, boundary_trade("120.0"), FOLLOWING], "1.000")

    assert filled == [("1.000", "120.0", START + MINUTE)]


@pytest.mark.characterization
@pytest.mark.integration
def test_bar_execution_offers_a_quarter_of_the_volume_per_price() -> None:
    filled = fills([SIGNAL, FOLLOWING], "50.000")

    assert filled == [
        ("25.000", "105.0", START + MINUTE),
        ("25.000", "105.1", START + MINUTE),
    ]
