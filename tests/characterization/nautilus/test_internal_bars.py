import pytest
from kit import INSTRUMENT_ID, START, run_engine
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    BarType,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)
from nautilus_trader.trading import Strategy

pytestmark = pytest.mark.characterization

MINUTE = 60_000_000_000
BAR_TYPE = BarType.from_str(f"{INSTRUMENT_ID}-1-MINUTE-LAST-INTERNAL")


class BarRecorder(Strategy):
    def on_start(self) -> None:
        self.bars: list[Bar] = []
        self.subscribe_bars(BAR_TYPE)

    def on_bar(self, bar: Bar) -> None:
        self.bars.append(bar)


def trade(index: int) -> TradeTick:
    ts = START + index * MINUTE // 2
    price = Price.from_str(f"{50000 + index}.0")
    size = Quantity.from_str("0.100")
    return TradeTick(
        INSTRUMENT_ID, price, size, AggressorSide.BUY, TradeId(str(index)), ts, ts
    )


def recorded_bars(trade_count: int) -> list[Bar]:
    recorder = BarRecorder()
    run_engine([trade(index) for index in range(trade_count)], recorder)
    return recorder.bars


def ohlcv(bar: Bar) -> tuple[str, str, str, str, str]:
    return (str(bar.open), str(bar.high), str(bar.low), str(bar.close), str(bar.volume))


def test_time_bars_close_on_the_right_and_include_the_boundary_trade() -> None:
    bars = recorded_bars(5)

    assert [bar.ts_event for bar in bars] == [START, START + MINUTE, START + 2 * MINUTE]
    assert [ohlcv(bar) for bar in bars] == [
        ("50000.0", "50000.0", "50000.0", "50000.0", "0.100"),
        ("50001.0", "50002.0", "50001.0", "50002.0", "0.200"),
        ("50003.0", "50004.0", "50003.0", "50004.0", "0.200"),
    ]


def test_trailing_partial_bar_is_not_emitted() -> None:
    assert len(recorded_bars(6)) == len(recorded_bars(5))


def test_a_bar_without_trades_repeats_the_close_with_zero_volume() -> None:
    recorder = BarRecorder()
    run_engine([trade(0), trade(5), trade(6)], recorder)

    assert [bar.ts_event for bar in recorder.bars] == [
        START + k * MINUTE for k in range(4)
    ]
    assert [ohlcv(bar) for bar in recorder.bars] == [
        ("50000.0", "50000.0", "50000.0", "50000.0", "0.100"),
        ("50000.0", "50000.0", "50000.0", "50000.0", "0.000"),
        ("50000.0", "50000.0", "50000.0", "50000.0", "0.000"),
        ("50005.0", "50006.0", "50005.0", "50006.0", "0.200"),
    ]
