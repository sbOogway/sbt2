"""Real candles, recorded from each exchange, in the raw file each source saves."""

import json
import zipfile
from pathlib import Path

import pytest
from binance_server import binance_replay
from coinbase_intx_replay import coinbase_intx_replay
from deribit_replay import deribit_replay
from kline_helpers import DAY_NANOS, MINUTE_NANOS, snapshot_instrument
from nautilus_stubs import load_sample
from nautilus_trader.model import Bar
from okx_client import okx_stubbed

from sbt2.data.sources import Source

HERE = Path(__file__).parent
FIRST_STAMP = DAY_NANOS + MINUTE_NANOS - 1


def ohlcv(bar: Bar) -> tuple[str, ...]:
    fields = (bar.open, bar.high, bar.low, bar.close, bar.volume)
    return tuple(str(each) for each in fields)


def parsed(source: Source, symbol: str, sample: Path, root: Path) -> list[Bar]:
    instrument = snapshot_instrument(source, symbol, root)
    return list(source.parse(sample, Bar, instrument))


@pytest.mark.unit
def test_a_recorded_binance_candle_sample_parses(tmp_path: Path) -> None:
    sample = tmp_path / "BTCUSDT2025-01-01.zip"
    with zipfile.ZipFile(sample, "w") as dump:
        dump.write(HERE / "binance_klines_sample.csv", "BTCUSDT-1m-2025-01-01.csv")
    with binance_replay() as binance:
        bars = parsed(binance, "BTCUSDT", sample, tmp_path)

    assert len(bars) == 3
    assert bars[0].ts_event == FIRST_STAMP
    assert ohlcv(bars[0]) == ("93548.80", "93599.90", "93514.20", "93599.90", "71.187")


@pytest.mark.unit
def test_a_recorded_okx_candle_sample_parses(tmp_path: Path) -> None:
    sample = tmp_path / "BTC-USDT-SWAP2025-01-01.json"
    sample.write_text(json.dumps(load_sample("okx_nautilus_sample.json")["bars"]))
    bars = parsed(okx_stubbed(), "BTC-USDT-SWAP", sample, tmp_path)

    assert len(bars) == 3
    assert bars[0].ts_event == FIRST_STAMP
    assert ohlcv(bars[0]) == ("93579.1", "93630.0", "93552.1", "93630.0", "3309.90")


@pytest.mark.unit
def test_a_recorded_coinbase_intx_candle_sample_parses(tmp_path: Path) -> None:
    sample = HERE / "coinbase_intx_candles_sample.json"
    with coinbase_intx_replay() as coinbase:
        bars = parsed(coinbase, "BTC-PERP", sample, tmp_path)

    assert len(bars) == 3
    assert bars[0].ts_event == FIRST_STAMP
    assert ohlcv(bars[0]) == ("93425.2", "93452.0", "93392.0", "93452.0", "42.5844")


@pytest.mark.unit
def test_a_recorded_deribit_candle_sample_parses(tmp_path: Path) -> None:
    sample = tmp_path / "BTC-PERPETUAL2025-01-01.json"
    sample.write_text((HERE / "deribit_chart_sample.json").read_text())
    with deribit_replay() as deribit:
        bars = parsed(deribit, "BTC-PERPETUAL", sample, tmp_path)

    assert len(bars) == 3
    assert bars[0].ts_event == FIRST_STAMP
    assert ohlcv(bars[0]) == ("93445.5", "93451.0", "93398.0", "93451.0", "1.38195605")
