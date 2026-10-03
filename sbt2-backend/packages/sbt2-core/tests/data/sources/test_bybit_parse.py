import asyncio
import gzip
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    FundingRateUpdate,
    MarkPriceUpdate,
    OrderBookDelta,
    TradeTick,
)

from sbt2.core.data.sources import (
    FundingOffGridError,
    RawFile,
    Source,
    UnsupportedDataTypeError,
)

DAY = date(2025, 1, 1)
DAY_NANOS = pd.Timestamp(DAY, tz="UTC").value
MINUTE_NANOS = 60_000_000_000

NEWEST_FIRST_TRADES = """\
timestamp,symbol,side,size,price,tickDirection,trdMatchID,grossValue,homeNotional,foreignNotional
1585267197.3539,BTCUSDT,Sell,0.857,6733.5,MinusTick,b7026545-8675-54e6-9935-6ed6b9d9993f,577060950000.0,0.857,5770.6095
1585267187.3512,BTCUSDT,Buy,0.18,6734.0,PlusTick,f9c156a9-5078-5681-bc96-708f5acd1cfa,121211999999.99998,0.18,1212.12
1585180818.434,BTCUSDT,Buy,0.09,6699.0,MinusTick,29087039-f48d-5df6-a9ae-2a6dca8dbb16,60291000000.0,0.09,602.91
"""


def saved(raw: RawFile, root: Path) -> Path:
    assert callable(raw.origin)
    path = root / raw.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(asyncio.run(raw.origin()))
    return path


@pytest.fixture
def instrument(replayed: Source, tmp_path: Path) -> Any:
    snapshot = saved(replayed.instrument_snapshot("BTCUSDT", DAY), tmp_path)
    return replayed.parse_instrument(snapshot)


@pytest.fixture
def trades_file(tmp_path: Path) -> Path:
    path = tmp_path / "BTCUSDT2020-03-26.csv.gz"
    path.write_bytes(gzip.compress(NEWEST_FIRST_TRADES.encode()))
    return path


@pytest.fixture
def funding_file(replayed: Source, tmp_path: Path) -> Path:
    return saved(replayed.day_file("BTCUSDT", FundingRateUpdate, DAY), tmp_path)


@pytest.mark.unit
def test_instrument_is_initialised_at_the_start_of_its_snapshot_day(
    instrument: Any,
) -> None:
    assert instrument.ts_init == DAY_NANOS
    assert str(instrument.margin_init) == "0.0066"


@pytest.mark.unit
def test_trades_come_in_time_order_with_exact_nanoseconds(
    bybit: Source, instrument: Any, trades_file: Path
) -> None:
    ticks = list(bybit.parse(trades_file, TradeTick, instrument))

    assert [each.ts_event for each in ticks] == [
        1585180818_434000000,
        1585267187_351200000,
        1585267197_353900000,
    ]
    assert all(each.ts_init == each.ts_event for each in ticks)


@pytest.mark.unit
def test_trades_keep_price_size_side_and_match_id(
    bybit: Source, instrument: Any, trades_file: Path
) -> None:
    tick = next(bybit.parse(trades_file, TradeTick, instrument))

    assert tick.instrument_id == instrument.id
    assert (str(tick.price), str(tick.size)) == ("6699.00", "0.090")
    assert tick.aggressor_side == AggressorSide.BUY
    assert str(tick.trade_id) == "29087039-f48d-5df6-a9ae-2a6dca8dbb16"


@pytest.mark.unit
def test_funding_without_interval_takes_the_instruments(
    bybit: Source, instrument: Any, funding_file: Path
) -> None:
    rates = list(bybit.parse(funding_file, FundingRateUpdate, instrument))

    assert [each.ts_event for each in rates] == [
        DAY_NANOS + hours * 60 * MINUTE_NANOS for hours in (0, 8, 16)
    ]
    assert [each.interval for each in rates] == [480, 480, 480]


@pytest.mark.unit
def test_funding_off_its_interval_grid_is_refused(
    bybit: Source, instrument: Any, funding_file: Path
) -> None:
    records = json.loads(funding_file.read_text())
    records[1]["ts_event"] += MINUTE_NANOS
    funding_file.write_text(json.dumps(records))

    with pytest.raises(FundingOffGridError):
        list(bybit.parse(funding_file, FundingRateUpdate, instrument))


@pytest.mark.unit
def test_mark_prices_are_each_minutes_close_just_before_its_end(
    replayed: Source, instrument: Any, tmp_path: Path
) -> None:
    klines = saved(replayed.day_file("BTCUSDT", MarkPriceUpdate, DAY), tmp_path)

    marks = list(replayed.parse(klines, MarkPriceUpdate, instrument))

    assert [each.ts_event for each in marks] == [
        DAY_NANOS + minute * MINUTE_NANOS - 1 for minute in range(1, 1441)
    ]
    assert (marks[719].ts_event, str(marks[719].value)) == (
        DAY_NANOS + 720 * MINUTE_NANOS - 1,
        "93396.41",
    )


@pytest.mark.unit
def test_candles_are_stamped_1_ns_before_their_close(
    replayed: Source, instrument: Any, tmp_path: Path
) -> None:
    candles = saved(replayed.day_file("BTCUSDT", Bar, DAY), tmp_path)

    bars = list(replayed.parse(candles, Bar, instrument))

    assert [(each.ts_event, each.ts_init) for each in (bars[0], bars[-1])] == [
        (DAY_NANOS + MINUTE_NANOS - 1,) * 2,
        (DAY_NANOS + 1440 * MINUTE_NANOS - 1,) * 2,
    ]
    assert str(bars[0]) == (
        "BTCUSDT-LINEAR.BYBIT-1-MINUTE-LAST-EXTERNAL,"
        f"93530.00,93590.80,93501.30,93590.50,30.284,{DAY_NANOS + MINUTE_NANOS - 1}"
    )


@pytest.mark.unit
def test_unparsed_data_type_is_refused(
    bybit: Source, instrument: Any, trades_file: Path
) -> None:
    with pytest.raises(UnsupportedDataTypeError):
        bybit.parse(trades_file, OrderBookDelta, instrument)
