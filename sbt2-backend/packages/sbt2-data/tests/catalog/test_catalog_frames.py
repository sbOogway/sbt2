from pathlib import Path
from typing import Any

import pytest
from local_catalog import DAY, days
from local_source import start_of
from nautilus_trader.model import (
    Bar,
    BarType,
    InstrumentId,
    MarkPriceUpdate,
    Price,
    Quantity,
)
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.data import Catalog
from sbt2.data.sources import candle_type

HOUR = 3_600_000_000_000
START = start_of(DAY)
BOUNDS = (START, START + 24 * HOUR - 1)
WINDOW = days(DAY, DAY)
IDS = tuple(
    InstrumentId.from_str(f"{symbol}-PERP.LOCAL") for symbol in ("BTC", "ETH", "SOL")
)


def mark(instrument_id: InstrumentId, hour: int, price: int) -> MarkPriceUpdate:
    ts = START + hour * HOUR
    return MarkPriceUpdate(instrument_id, Price.from_int(price), ts, ts)


def candle(bar_type: BarType, hour: int, price: int) -> Bar:
    ts = START + hour * HOUR
    value = Price.from_int(price)
    return Bar(bar_type, value, value, value, value, Quantity.from_int(1), ts, ts)


def marks_catalog(path: Path, instrument_ids: tuple[InstrumentId, ...]) -> Catalog:
    nautilus = ParquetDataCatalog(str(path))
    for index, each in enumerate(instrument_ids):
        marks = [mark(each, hour, 100 * index + hour) for hour in range(3)]
        nautilus.write_mark_price_updates(marks, *BOUNDS)
    return Catalog(path)


@pytest.fixture
def queries(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    query = ParquetDataCatalog.query

    def counted(self: ParquetDataCatalog, *args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return query(self, *args, **kwargs)

    monkeypatch.setattr(ParquetDataCatalog, "query", counted)
    return calls


@pytest.mark.integration
def test_frames_read_many_instruments_in_one_query(
    tmp_path: Path, queries: list[Any]
) -> None:
    catalog = marks_catalog(tmp_path, IDS)

    frames = catalog.frames(IDS, MarkPriceUpdate, WINDOW)

    assert len(queries) == 1
    for each in IDS:
        expected = catalog.frame(each, MarkPriceUpdate, WINDOW)
        assert frames[each].equals(expected)
        assert len(frames[each]) == 3


@pytest.mark.integration
def test_frames_give_an_empty_frame_for_an_instrument_without_records(
    tmp_path: Path,
) -> None:
    catalog = marks_catalog(tmp_path, IDS[:1])

    frames = catalog.frames(IDS[:2], MarkPriceUpdate, WINDOW)

    expected = catalog.frame(IDS[0], MarkPriceUpdate, WINDOW)
    assert frames[IDS[1]].empty
    assert list(frames[IDS[1]].columns) == list(expected.columns)
    assert frames[IDS[1]].index.name == "ts_event"


@pytest.mark.integration
def test_frames_split_candles_by_instrument(tmp_path: Path) -> None:
    nautilus = ParquetDataCatalog(str(tmp_path))
    for index, each in enumerate(IDS[:2]):
        bars = [candle(candle_type(each), hour, 100 + index) for hour in range(2)]
        nautilus.write_bars(bars, *BOUNDS)

    frames = Catalog(tmp_path).frames(IDS[:2], Bar, WINDOW)

    assert list(frames[IDS[0]]["close"]) == [100.0, 100.0]
    assert list(frames[IDS[1]]["close"]) == [101.0, 101.0]


@pytest.mark.integration
def test_frames_of_no_instruments_make_no_query(
    tmp_path: Path, queries: list[Any]
) -> None:
    assert Catalog(tmp_path).frames((), MarkPriceUpdate, WINDOW) == {}
    assert queries == []
