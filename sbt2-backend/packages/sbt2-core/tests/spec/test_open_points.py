from datetime import timedelta
from pathlib import Path

import pytest
from candle_catalog import Candle, write_candles
from deribit_perpetual_catalog import perpetual
from feeds_catalog import BINANCE, feed_perpetual
from nautilus_trader.model import AggressorSide, NautilusDataType, TradeTick
from nautilus_trader.persistence import ParquetDataCatalog
from synthetic_catalog import START
from synthetic_catalog import perpetual as linear_perpetual

from sbt2.core.assets import QuoteJob
from sbt2.core.spec import load
from sbt2.core.spec.bars import bar_source

NEXT_OPEN = {"fills": "next_open"}
WINDOW = (START, START + timedelta(days=1))
FEED_SPEC = """
strategy = "feed_strategies:Listener"
instruments = ["BTC-PERPETUAL.DERIBIT"]
period = [2024-01-01, 2024-01-04]
split = { validation_start = 2024-01-02, test_start = 2024-01-03 }
part = "train"
bars = "candles"
execution = { fee_model = { kind = "maker_taker", config = { maker_rate = "0.00015", taker_rate = "0.00035" } } }
capital = "1 BTC"
"""


def opens_folder(tmp_path: Path) -> Path:
    """The run's temporary folder, which exists before anything is written."""
    folder = tmp_path / "opens"
    folder.mkdir()
    return folder


def open_points(folder: Path) -> list[TradeTick]:
    return ParquetDataCatalog(str(folder)).query(NautilusDataType.TradeTick)


def write_opens(tmp_path: Path) -> list[TradeTick]:
    job = QuoteJob(tmp_path / "catalog", [linear_perpetual().id], WINDOW, NEXT_OPEN)
    folder = opens_folder(tmp_path)
    bar_source("candles").write_fills(job, folder)
    return open_points(folder)


@pytest.mark.integration
def test_open_points_sit_at_each_candle_open(tmp_path: Path) -> None:
    candles = [
        Candle(0, (100.0, 110.0, 90.0, 105.0), volume=8.0),
        Candle(1, (120.0, 130.0, 115.0, 125.0), volume=10.0),
        Candle(3, (140.0, 150.0, 135.0, 145.0), volume=0.0),
        Candle(4, (160.0, 170.0, 155.0, 165.0), volume=2.0),
    ]
    write_candles(tmp_path / "catalog", linear_perpetual(), candles)

    points = write_opens(tmp_path)

    expected = [candles[0], candles[1], candles[3]]
    assert [each.ts_event for each in points] == [each.opens_at for each in expected]
    assert [each.ts_init for each in points] == [each.opens_at for each in expected]
    assert [str(each.price) for each in points] == ["100.0", "120.0", "160.0"]
    assert [str(each.size) for each in points] == ["2.000", "2.500", "0.500"]
    assert {each.aggressor_side for each in points} == {AggressorSide.NO_AGGRESSOR}
    assert [str(each.trade_id) for each in points] == [
        str(each.opens_at) for each in expected
    ]


@pytest.mark.integration
def test_an_open_point_has_at_least_one_size_increment(tmp_path: Path) -> None:
    write_candles(
        tmp_path / "catalog",
        linear_perpetual(),
        [Candle(0, (100.0, 110.0, 90.0, 105.0), volume=0.001)],
    )

    [point] = write_opens(tmp_path)

    assert str(point.size) == "0.001"


@pytest.mark.integration
def test_open_points_are_only_for_traded_instruments_inside_the_window(
    tmp_path: Path,
) -> None:
    catalog = tmp_path / "catalog"
    prices = (50_000.0, 50_000.0, 50_000.0, 50_000.0)
    minutes = [
        Candle(minute, prices, volume=1000.0)
        for minute in (-60, -1, 0, 1, 1438, 1439, 1440, 1441)
    ]
    write_candles(catalog, perpetual(), minutes)
    write_candles(catalog, feed_perpetual(BINANCE, "1"), minutes)
    spec = tmp_path / "spec.toml"
    spec.write_text(FEED_SPEC)
    [resolved] = load(spec)
    folder = opens_folder(tmp_path)

    configs = bar_source("candles").write_fills(resolved.quote_job(catalog), folder)

    assert resolved.data_window == WINDOW
    points = open_points(folder)
    assert {each.instrument_id for each in points} == {perpetual().id}
    assert [each.ts_event for each in points] == [
        each.opens_at for each in minutes[2:6]
    ]
    [config] = configs
    assert config.data_type == NautilusDataType.TradeTick
    assert config.instrument_ids == [perpetual().id]


@pytest.mark.integration
def test_close_fills_write_no_open_points(tmp_path: Path) -> None:
    write_candles(
        tmp_path / "catalog",
        linear_perpetual(),
        [Candle(0, (100.0, 110.0, 90.0, 105.0))],
    )
    job = QuoteJob(
        tmp_path / "catalog", [linear_perpetual().id], WINDOW, {"fills": "close"}
    )

    folder = opens_folder(tmp_path)

    assert bar_source("candles").write_fills(job, folder) == []
    assert list(folder.iterdir()) == []


@pytest.mark.unit
def test_trade_bars_write_no_fill_data(tmp_path: Path) -> None:
    job = QuoteJob(tmp_path / "catalog", [linear_perpetual().id], WINDOW, {})

    folder = opens_folder(tmp_path)

    assert bar_source("trades").write_fills(job, folder) == []
    assert list(folder.iterdir()) == []
