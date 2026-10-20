import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from kline_helpers import (
    CLOSES,
    DAY,
    DAY_NANOS,
    MINUTE_NANOS,
    downloaded,
    snapshot_instrument,
)
from nautilus_trader.model import Bar, CryptoPerpetual
from okx_client import okx_stub, okx_stubbed

from sbt2.data import Outcome
from sbt2.data.sources import MissingAtSourceError
from sbt2.data.sources.okx import OkxSource

BTC_SWAP = "BTC-USDT-SWAP"


@pytest.mark.unit
def test_okx_klines_parse_into_one_minute_bars(tmp_path: Path) -> None:
    okx = okx_stubbed()
    downloaded(okx, BTC_SWAP, tmp_path)
    instrument = snapshot_instrument(okx, BTC_SWAP, tmp_path)
    candles = tmp_path / okx.day_file(BTC_SWAP, Bar, DAY).path

    bars = list(okx.parse(candles, Bar, instrument))

    assert len(bars) == 1440
    first = bars[0]
    assert str(first.bar_type) == "BTC-USDT-SWAP.OKX-1-MINUTE-LAST-EXTERNAL"
    assert first.ts_event == DAY_NANOS + MINUTE_NANOS - 1
    assert first.ts_init == first.ts_event
    assert bars[-1].ts_event == DAY_NANOS + 1440 * MINUTE_NANOS - 1
    assert all(each.high >= each.low for each in bars)
    assert first.volume.as_double() > 0


@pytest.mark.integration
def test_a_day_of_okx_klines_is_downloaded_in_pages_without_duplicates(
    tmp_path: Path,
) -> None:
    stub = okx_stub()
    okx = OkxSource(frozenset(), stub)
    assert downloaded(okx, BTC_SWAP, tmp_path) == [Outcome.FETCHED] * 2
    instrument = snapshot_instrument(okx, BTC_SWAP, tmp_path)
    candles = tmp_path / okx.day_file(BTC_SWAP, Bar, DAY).path

    stamps = [each.ts_event for each in okx.parse(candles, Bar, instrument)]

    assert stamps == CLOSES
    assert len(stub.windows) == 15
    first = datetime(2025, 1, 1, tzinfo=UTC)
    assert stub.windows[0] == (first - timedelta(milliseconds=1), first + timedelta(1))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("symbol", "base", "contract_size"),
    [(BTC_SWAP, "BTC", "0.01"), ("ETH-USDT-SWAP", "ETH", "0.1")],
)
def test_okx_perpetual_instrument_gives_the_volume_unit(
    tmp_path: Path, symbol: str, base: str, contract_size: str
) -> None:
    okx = okx_stubbed()
    assert okx.symbol(okx.instrument_id(symbol)) == symbol

    instrument = snapshot_instrument(okx, symbol, tmp_path)

    assert isinstance(instrument, CryptoPerpetual)
    assert not instrument.is_inverse
    assert str(instrument.base_currency) == base
    assert str(instrument.quote_currency) == "USDT"
    assert str(instrument.multiplier) == contract_size


@pytest.mark.unit
def test_an_unlisted_okx_symbol_is_missing_at_the_source() -> None:
    okx = okx_stubbed()
    raw = okx.day_file("NOPE-USDT-SWAP", Bar, DAY)
    assert callable(raw.origin)
    with pytest.raises(MissingAtSourceError, match="NOPE-USDT-SWAP"):
        asyncio.run(raw.origin())


@pytest.mark.unit
def test_a_day_before_the_listing_is_missing_at_the_source() -> None:
    okx = okx_stubbed()
    raw = okx.day_file(BTC_SWAP, Bar, DAY - timedelta(days=30))
    assert callable(raw.origin)
    with pytest.raises(MissingAtSourceError, match="candles on 2024-12-02"):
        asyncio.run(raw.origin())
