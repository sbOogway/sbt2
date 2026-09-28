from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from local_catalog import DAY, LocalCatalog, days, midnight
from local_source import INSTRUMENT_ID, perpetual, start_of
from nautilus_trader.model import (
    AggressorSide,
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


def test_trades_load_as_a_frame_indexed_by_event_time(tmp_path: Path) -> None:
    sell = trade(1, START + MINUTE, AggressorSide.SELL)
    catalog = trades_catalog(tmp_path, [trade(0, START), sell])

    frame = catalog.trades(INSTRUMENT_ID, DAY_WINDOW)

    assert frame.index.name == "ts_event"
    assert list(frame.index) == [utc(START), utc(START + MINUTE)]
    assert frame.to_dict("list") == {
        "price": [50000.0, 50001.0],
        "size": [0.1, 0.1],
        "side": ["BUY", "SELL"],
        "trade_id": ["0", "1"],
    }


def test_loaders_keep_to_the_window(tmp_path: Path) -> None:
    catalog = trades_catalog(tmp_path, trades_every_half_minute(6))
    window = Window(
        midnight(DAY) + timedelta(seconds=30), midnight(DAY) + timedelta(minutes=2)
    )

    frame = catalog.trades(INSTRUMENT_ID, window)

    assert list(frame["trade_id"]) == ["1", "2", "3"]


def test_mark_prices_load_as_a_frame(tmp_path: Path) -> None:
    catalog = ParquetDataCatalog(str(tmp_path))
    catalog.write_instruments([perpetual()])
    marks = [
        MarkPriceUpdate(INSTRUMENT_ID, Price.from_str(price), ts, ts)
        for price, ts in [("50000.0", START), ("50000.5", START + MINUTE)]
    ]
    catalog.write_mark_price_updates(marks, *BOUNDS)

    frame = Catalog(tmp_path).mark_prices(INSTRUMENT_ID, DAY_WINDOW)

    assert frame.index.name == "ts_event"
    assert list(frame.index) == [utc(START), utc(START + MINUTE)]
    assert frame.to_dict("list") == {"price": [50000.0, 50000.5]}


def test_funding_loads_as_a_frame(tmp_path: Path) -> None:
    eight_hours = 8 * 60 * MINUTE
    local = LocalCatalog(tmp_path)
    local.write(FundingRateUpdate, DAY, [START + k * eight_hours for k in range(3)])

    frame = Catalog(local.path).funding(INSTRUMENT_ID, DAY_WINDOW)

    assert frame.index.name == "ts_event"
    assert list(frame.index) == [utc(START + k * eight_hours) for k in range(3)]
    assert frame.to_dict("list") == {"rate": [0.0001] * 3, "interval": [480] * 3}


def test_an_empty_window_loads_an_empty_frame_with_the_columns(
    tmp_path: Path,
) -> None:
    catalog = trades_catalog(tmp_path, trades_every_half_minute(2))
    evening = midnight(DAY) + timedelta(hours=20)

    frame = catalog.trades(INSTRUMENT_ID, Window(evening, evening + timedelta(hours=1)))

    assert frame.empty
    assert list(frame.columns) == ["price", "size", "side", "trade_id"]


def test_bars_close_on_the_right_like_nautilus(tmp_path: Path) -> None:
    catalog = trades_catalog(tmp_path, trades_every_half_minute(5))

    bars = catalog.bars(INSTRUMENT_ID, DAY_WINDOW, timedelta(minutes=1))

    assert bars.index.name == "ts_event"
    assert list(bars.index) == [
        utc(START),
        utc(START + MINUTE),
        utc(START + 2 * MINUTE),
    ]
    assert bars.to_dict("list") == {
        "open": [50000.0, 50001.0, 50003.0],
        "high": [50000.0, 50002.0, 50004.0],
        "low": [50000.0, 50001.0, 50003.0],
        "close": [50000.0, 50002.0, 50004.0],
        "volume": [0.1, 0.2, 0.2],
    }


def test_a_minute_without_trades_repeats_the_close_with_zero_volume(
    tmp_path: Path,
) -> None:
    trades = [trade(0, START), trade(1, START + 5 * HALF_MINUTE)]
    catalog = trades_catalog(tmp_path, trades)

    bars = catalog.bars(INSTRUMENT_ID, DAY_WINDOW, timedelta(minutes=1))

    assert list(bars.index) == [utc(START + k * MINUTE) for k in range(4)]
    assert bars.to_dict("list") == {
        "open": [50000.0, 50000.0, 50000.0, 50001.0],
        "high": [50000.0, 50000.0, 50000.0, 50001.0],
        "low": [50000.0, 50000.0, 50000.0, 50001.0],
        "close": [50000.0, 50000.0, 50000.0, 50001.0],
        "volume": [0.1, 0.0, 0.0, 0.1],
    }
