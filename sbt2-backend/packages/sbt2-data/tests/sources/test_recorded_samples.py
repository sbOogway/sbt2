"""Real candles, recorded from each exchange, in the raw file each source saves."""

import asyncio
import json
import zipfile
from pathlib import Path

import pytest
from binance_server import binance_replay
from coinbase_intx_replay import coinbase_intx_replay
from deribit_replay import deribit_replay
from kline_helpers import DAY_NANOS, MINUTE_NANOS, SNAPSHOT_DAY, snapshot_instrument
from nautilus_stubs import load_sample
from nautilus_trader.model import Bar, InstrumentId
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
    sample.write_text(json.dumps(load_sample("deribit_nautilus_sample.json")))
    with deribit_replay() as deribit:
        bars = parsed(deribit, "BTC-PERPETUAL", sample, tmp_path)

    assert len(bars) == 3
    assert bars[0].ts_event == FIRST_STAMP
    assert ohlcv(bars[0]) == ("93445.5", "93451.0", "93398.0", "93451.0", "129120")


def parsed_day(
    source: Source, symbol: str, sample: Path, root: Path
) -> dict[InstrumentId, list[Bar]]:
    raw = source.instrument_snapshot(symbol, SNAPSHOT_DAY)
    assert callable(raw.origin)
    snapshot = root / raw.path
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(asyncio.run(raw.origin()))
    instruments = source.parse_instruments(snapshot)
    ids = source.day_instrument_ids(sample, Bar, instruments)
    day = source.parse_day(sample, Bar, {each: instruments[each] for each in ids})
    return {each: list(bars) for each, bars in day.items()}


@pytest.mark.unit
def test_parse_a_recorded_sample_of_real_future_and_spot_candles(
    tmp_path: Path,
) -> None:
    futures = tmp_path / "BTC-FUTURES2025-01-01.json"
    futures.write_text(json.dumps(load_sample("deribit_future_nautilus_sample.json")))
    spot = tmp_path / "BTC_USDC2025-01-01.json"
    spot.write_text(json.dumps(load_sample("deribit_spot_chart_sample.json")))
    with deribit_replay() as deribit:
        by_future = parsed_day(deribit, "BTC-FUTURES", futures, tmp_path)
        by_pair = parsed_day(deribit, "BTC_USDC", spot, tmp_path)

    assert {str(each): len(bars) for each, bars in by_future.items()} == {
        "BTC-10JAN25.DERIBIT": 3,
        "BTC-3JAN25.DERIBIT": 3,
    }
    january_3 = by_future[InstrumentId.from_str("BTC-3JAN25.DERIBIT")]
    assert january_3[0].ts_event == FIRST_STAMP
    assert ohlcv(january_3[0]) == ("93512.5", "93557.5", "93512.5", "93557.5", "1510")
    ((_, pair),) = by_pair.items()
    assert [each.ts_event for each in pair] == [
        DAY_NANOS + n * MINUTE_NANOS - 1 for n in (1, 2, 3)
    ]
    assert ohlcv(pair[0]) == (
        "93370.00",
        "93400.00",
        "93370.00",
        "93400.00",
        "0.71480000",
    )
