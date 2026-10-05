from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from local_catalog import DAY, LocalCatalog, days, midnight
from local_source import CANDLE_TYPE, INSTRUMENT_ID, perpetual, start_of
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    FundingRateUpdate,
    MarkPriceUpdate,
    Price,
    Quantity,
    TradeId,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.data import Catalog, Window

MINUTE = 60_000_000_000
HALF_MINUTE = MINUTE // 2
START = start_of(DAY)
BOUNDS = (START, START + 24 * 60 * MINUTE - 1)
DAY_WINDOW = days(DAY, DAY)


def trade(index: int, ts: int, side: AggressorSide = AggressorSide.BUY) -> TradeTick:
    return TradeTick(
        INSTRUMENT_ID,
        Price.from_str(f"{50000 + index}.0"),
        Quantity.from_str("0.100"),
        side,
        TradeId(str(index)),
        ts,
        ts,
    )


def trades_every_half_minute(count: int) -> list[TradeTick]:
    return [trade(index, START + index * HALF_MINUTE) for index in range(count)]


def trades_catalog(path: Path, trades: Sequence[TradeTick]) -> Catalog:
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([perpetual()])
    catalog.write_trade_ticks(list(trades), *BOUNDS)
    return Catalog(path)


def utc(ts: int) -> datetime:
    return midnight(DAY) + timedelta(microseconds=(ts - START) // 1000)


@pytest.mark.unit
def test_trades_load_as_a_frame_indexed_by_event_time(tmp_path: Path) -> None:
    sell = trade(1, START + MINUTE, AggressorSide.SELL)
    catalog = trades_catalog(tmp_path, [trade(0, START), sell])

    frame = catalog.frame(INSTRUMENT_ID, TradeTick, DAY_WINDOW)

    assert frame.index.name == "ts_event"
    assert list(frame.index) == [utc(START), utc(START + MINUTE)]
    assert frame.to_dict("list") == {
        "price": [50000.0, 50001.0],
        "size": [0.1, 0.1],
        "side": ["BUY", "SELL"],
        "trade_id": ["0", "1"],
    }


@pytest.mark.unit
def test_loaders_keep_to_the_window(tmp_path: Path) -> None:
    catalog = trades_catalog(tmp_path, trades_every_half_minute(6))
    window = Window(
        midnight(DAY) + timedelta(seconds=30), midnight(DAY) + timedelta(minutes=2)
    )

    frame = catalog.frame(INSTRUMENT_ID, TradeTick, window)

    assert list(frame["trade_id"]) == ["1", "2", "3"]


@pytest.mark.unit
def test_mark_prices_load_as_a_frame(tmp_path: Path) -> None:
    catalog = ParquetDataCatalog(str(tmp_path))
    catalog.write_instruments([perpetual()])
    marks = [
        MarkPriceUpdate(INSTRUMENT_ID, Price.from_str(price), ts, ts)
        for price, ts in [("50000.0", START), ("50000.5", START + MINUTE)]
    ]
    catalog.write_mark_price_updates(marks, *BOUNDS)

    frame = Catalog(tmp_path).frame(INSTRUMENT_ID, MarkPriceUpdate, DAY_WINDOW)

    assert frame.index.name == "ts_event"
    assert list(frame.index) == [utc(START), utc(START + MINUTE)]
    assert frame.to_dict("list") == {"price": [50000.0, 50000.5]}


@pytest.mark.unit
def test_funding_loads_as_a_frame(tmp_path: Path) -> None:
    eight_hours = 8 * 60 * MINUTE
    local = LocalCatalog(tmp_path)
    local.write(FundingRateUpdate, DAY, [START + k * eight_hours for k in range(3)])

    frame = Catalog(local.path).frame(INSTRUMENT_ID, FundingRateUpdate, DAY_WINDOW)

    assert frame.index.name == "ts_event"
    assert list(frame.index) == [utc(START + k * eight_hours) for k in range(3)]
    assert frame.to_dict("list") == {"rate": [0.0001] * 3, "interval": [480] * 3}


def candle(minute: int, ohlc: str, volume: str) -> Bar:
    open_, high, low, close = (Price.from_str(each) for each in ohlc.split())
    ts = START + (minute + 1) * MINUTE - 1
    return Bar(CANDLE_TYPE, open_, high, low, close, Quantity.from_str(volume), ts, ts)


@pytest.mark.unit
def test_candles_load_as_a_frame_of_ohlcv(tmp_path: Path) -> None:
    catalog = ParquetDataCatalog(str(tmp_path))
    catalog.write_instruments([perpetual()])
    candles = [
        candle(0, "50000.0 50010.0 49990.0 50005.0", "1.500"),
        candle(1, "50005.0 50005.0 50005.0 50005.0", "0.000"),
    ]
    catalog.write_bars(candles, *BOUNDS)

    frame = Catalog(tmp_path).frame(INSTRUMENT_ID, Bar, DAY_WINDOW)

    assert frame.index.name == "ts_event"
    assert [each.value for each in frame.index] == [
        START + k * MINUTE - 1 for k in (1, 2)
    ]
    assert frame.to_dict("list") == {
        "open": [50000.0, 50005.0],
        "high": [50010.0, 50005.0],
        "low": [49990.0, 50005.0],
        "close": [50005.0, 50005.0],
        "volume": [1.5, 0.0],
    }


@pytest.mark.unit
def test_an_empty_window_loads_an_empty_frame_with_the_columns(
    tmp_path: Path,
) -> None:
    catalog = trades_catalog(tmp_path, trades_every_half_minute(2))
    evening = midnight(DAY) + timedelta(hours=20)

    frame = catalog.frame(
        INSTRUMENT_ID, TradeTick, Window(evening, evening + timedelta(hours=1))
    )

    assert frame.empty
    assert list(frame.columns) == ["price", "size", "side", "trade_id"]
