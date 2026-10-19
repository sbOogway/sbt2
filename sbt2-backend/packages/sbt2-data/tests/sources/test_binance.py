import asyncio
from pathlib import Path

import pytest
from binance_server import binance_replay
from kline_helpers import (
    CLOSES,
    DAY,
    DAY_NANOS,
    MINUTE_NANOS,
    downloaded,
    snapshot_instrument,
)
from nautilus_trader.model import Bar, CryptoPerpetual, InstrumentId

from sbt2.data import DayRange, DownloadOptions, DownloadRequest, Outcome, download
from sbt2.data.sources import MissingAtSourceError

BTC_PERP = InstrumentId.from_str("BTCUSDT-PERP.BINANCE")


@pytest.mark.unit
def test_binance_klines_parse_into_one_minute_bars(tmp_path: Path) -> None:
    with binance_replay() as binance:
        downloaded(binance, "BTCUSDT", tmp_path)
        instrument = snapshot_instrument(binance, "BTCUSDT", tmp_path)
        dump = tmp_path / binance.day_file("BTCUSDT", Bar, DAY).path

        bars = list(binance.parse(dump, Bar, instrument))

    assert len(bars) == 1440
    first = bars[0]
    assert str(first.bar_type) == "BTCUSDT-PERP.BINANCE-1-MINUTE-LAST-EXTERNAL"
    assert (str(first.open), str(first.high), str(first.low), str(first.close)) == (
        "93548.80",
        "93599.90",
        "93514.20",
        "93599.90",
    )
    assert str(first.volume) == "71.187"
    assert first.ts_event == DAY_NANOS + MINUTE_NANOS - 1
    assert bars[-1].ts_event == DAY_NANOS + 1440 * MINUTE_NANOS - 1


@pytest.mark.integration
def test_a_day_of_binance_klines_is_downloaded(tmp_path: Path) -> None:
    with binance_replay() as binance:
        assert downloaded(binance, "BTCUSDT", tmp_path) == [Outcome.FETCHED] * 2
        instrument = snapshot_instrument(binance, "BTCUSDT", tmp_path)
        dump = tmp_path / binance.day_file("BTCUSDT", Bar, DAY).path

        stamps = [each.ts_event for each in binance.parse(dump, Bar, instrument)]

    assert stamps == CLOSES


@pytest.mark.unit
def test_binance_perpetual_instrument_gives_the_volume_unit(tmp_path: Path) -> None:
    with binance_replay() as binance:
        assert binance.instrument_id("BTCUSDT") == BTC_PERP
        assert binance.symbol(BTC_PERP) == "BTCUSDT"

        instrument = snapshot_instrument(binance, "BTCUSDT", tmp_path)

    assert isinstance(instrument, CryptoPerpetual)
    assert not instrument.is_inverse
    assert str(instrument.base_currency) == "BTC"
    assert str(instrument.quote_currency) == "USDT"
    assert str(instrument.multiplier) == "1"
    assert str(instrument.size_increment) == "0.001"
    assert str(instrument.price_increment) == "0.10"


@pytest.mark.integration
def test_a_binance_dump_with_a_bad_checksum_is_refused(tmp_path: Path) -> None:
    bad = b"0" * 64 + b"  BTCUSDT-1m-2025-01-01.zip\n"
    with binance_replay(checksum=bad) as binance:
        request = DownloadRequest(DayRange(("BTCUSDT",), DAY, DAY))
        options = DownloadOptions(tmp_path, retries=0, backoff=0.0)

        results = download(binance, request, options).results

    (result,) = (each for each in results if each.item.data == "Bar")
    assert result.outcome == Outcome.FAILED
    assert "checksum" in result.reason
    assert not (tmp_path / binance.day_file("BTCUSDT", Bar, DAY).path).exists()


@pytest.mark.unit
def test_an_unlisted_binance_symbol_is_missing_at_the_source() -> None:
    with binance_replay() as binance:
        raw = binance.instrument_snapshot("NOPEUSDT", DAY)
        assert callable(raw.origin)
        with pytest.raises(MissingAtSourceError, match="NOPEUSDT"):
            asyncio.run(raw.origin())
