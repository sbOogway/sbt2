"""Downloads a real recent day of 1-minute klines from each exchange and parses
it; run with ``pytest -m live``."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model import Bar

from sbt2.data import DayRange, DownloadOptions, DownloadRequest, Outcome, download
from sbt2.data.sources import source

RECENT = datetime.now(UTC).date() - timedelta(days=3)
# Coinbase International has served no candle since its BTC-PERP paused on 2026-10-01.
COINBASE_LAST = date(2026, 9, 15)


@pytest.mark.live
@pytest.mark.e2e
@pytest.mark.parametrize(
    ("name", "symbol", "instrument_id", "day"),
    [
        ("binance", "BTCUSDT", "BTCUSDT-PERP.BINANCE", RECENT),
        ("okx", "BTC-USDT-SWAP", "BTC-USDT-SWAP.OKX", RECENT),
        ("coinbase_intx", "BTC-PERP", "BTC-PERP.COINBASE_INTX", COINBASE_LAST),
        ("deribit", "BTC-PERPETUAL", "BTC-PERPETUAL.DERIBIT", RECENT),
        ("bybit", "ETHUSDT", "ETHUSDT-LINEAR.BYBIT", RECENT),
    ],
)
def test_a_real_day_of_klines_is_downloaded_and_parsed(
    tmp_path: Path, name: str, symbol: str, instrument_id: str, day: date
) -> None:
    exchange = source(name, tmp_path / "known_gaps.toml")
    days = DayRange((symbol,), day, day, ("Bar",))
    request = DownloadRequest(days, day)

    tally = download(exchange, request, DownloadOptions(tmp_path))

    assert {each.outcome for each in tally.results} == {Outcome.FETCHED}, tally
    snapshot = tmp_path / exchange.instrument_snapshot(symbol, day).path
    instrument = exchange.parse_instruments(snapshot)[exchange.instrument_id(symbol)]
    candles = tmp_path / exchange.day_file(symbol, Bar, day).path
    stamps = [each.ts_event for each in exchange.parse(candles, Bar, instrument)]
    assert str(instrument.id) == instrument_id
    assert stamps == sorted(set(stamps))
    assert 1000 <= len(stamps) <= 1440
    start = pd.Timestamp(day, tz="UTC").value
    assert start <= stamps[0]
    assert stamps[-1] < start + pd.Timedelta(days=1).value
