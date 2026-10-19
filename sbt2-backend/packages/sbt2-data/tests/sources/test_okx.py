import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from nautilus_trader.model import Bar, CryptoPerpetual, InstrumentId
from okx_replay import okx_replay

from sbt2.data import DayRange, DownloadOptions, DownloadRequest, Outcome, download
from sbt2.data.sources import MissingAtSourceError, Source

DAY = date(2025, 1, 1)
SNAPSHOT_DAY = date(2026, 10, 19)
BTC_SWAP = InstrumentId.from_str("BTC-USDT-SWAP.OKX")
DAY_NANOS = pd.Timestamp(DAY, tz="UTC").value
MINUTE_NANOS = 60_000_000_000


def fetch(source: Source, symbol: str, root: Path) -> list[Outcome]:
    request = DownloadRequest(DayRange((symbol,), DAY, DAY), SNAPSHOT_DAY)
    tally = download(source, request, DownloadOptions(root, retries=0, backoff=0.0))
    return [each.outcome for each in tally.results]


def instrument_of(source: Source, symbol: str, root: Path) -> Any:
    raw = source.instrument_snapshot(symbol, SNAPSHOT_DAY)
    assert callable(raw.origin)
    snapshot = root / raw.path
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(asyncio.run(raw.origin()))
    return source.parse_instruments(snapshot)[source.instrument_id(symbol)]


@pytest.mark.unit
def test_okx_klines_parse_into_one_minute_bars(tmp_path: Path) -> None:
    with okx_replay() as okx:
        fetch(okx, "BTC-USDT-SWAP", tmp_path)
        instrument = instrument_of(okx, "BTC-USDT-SWAP", tmp_path)
        candles = tmp_path / okx.day_file("BTC-USDT-SWAP", Bar, DAY).path

        bars = list(okx.parse(candles, Bar, instrument))

    assert len(bars) == 1440
    first = bars[0]
    assert str(first.bar_type) == "BTC-USDT-SWAP.OKX-1-MINUTE-LAST-EXTERNAL"
    assert first.ts_event == DAY_NANOS + MINUTE_NANOS - 1
    assert bars[-1].ts_event == DAY_NANOS + 1440 * MINUTE_NANOS - 1
    assert all(each.high >= each.low for each in bars)
    assert first.volume.as_double() > 0


@pytest.mark.integration
def test_a_day_of_okx_klines_is_downloaded(tmp_path: Path) -> None:
    with okx_replay() as okx:
        assert fetch(okx, "BTC-USDT-SWAP", tmp_path) == [Outcome.FETCHED] * 2
        instrument = instrument_of(okx, "BTC-USDT-SWAP", tmp_path)
        candles = tmp_path / okx.day_file("BTC-USDT-SWAP", Bar, DAY).path

        stamps = [each.ts_event for each in okx.parse(candles, Bar, instrument)]

    assert stamps == [DAY_NANOS + n * MINUTE_NANOS - 1 for n in range(1, 1441)]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("symbol", "base", "contract_size"),
    [("BTC-USDT-SWAP", "BTC", "0.01"), ("ETH-USDT-SWAP", "ETH", "0.1")],
)
def test_okx_perpetual_instrument_gives_the_volume_unit(
    tmp_path: Path, symbol: str, base: str, contract_size: str
) -> None:
    with okx_replay() as okx:
        okx_symbol = okx.symbol(okx.instrument_id(symbol))

        instrument = instrument_of(okx, symbol, tmp_path)

    assert okx_symbol == symbol
    assert isinstance(instrument, CryptoPerpetual)
    assert not instrument.is_inverse
    assert str(instrument.base_currency) == base
    assert str(instrument.quote_currency) == "USDT"
    assert str(instrument.multiplier) == contract_size


@pytest.mark.unit
def test_an_unlisted_okx_symbol_is_missing_at_the_source() -> None:
    with okx_replay() as okx:
        raw = okx.day_file("NOPE-USDT-SWAP", Bar, DAY)
        assert callable(raw.origin)
        with pytest.raises(MissingAtSourceError, match="NOPE-USDT-SWAP"):
            asyncio.run(raw.origin())
