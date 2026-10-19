import asyncio
from pathlib import Path

import pytest
from coinbase_intx_replay import coinbase_intx_replay
from kline_helpers import (
    DAY,
    DAY_NANOS,
    MINUTE_NANOS,
    downloaded,
    snapshot_instrument,
)
from nautilus_trader.model import Bar, CryptoPerpetual

from sbt2.data import Outcome
from sbt2.data.sources import MissingAtSourceError

BTC_PERP = "BTC-PERP"


@pytest.mark.unit
def test_coinbase_intx_klines_parse_into_one_minute_bars(tmp_path: Path) -> None:
    with coinbase_intx_replay() as coinbase:
        downloaded(coinbase, BTC_PERP, tmp_path)
        instrument = snapshot_instrument(coinbase, BTC_PERP, tmp_path)
        candles = tmp_path / coinbase.day_file(BTC_PERP, Bar, DAY).path

        bars = list(coinbase.parse(candles, Bar, instrument))

    first = bars[0]
    assert str(first.bar_type) == "BTC-PERP.COINBASE_INTX-1-MINUTE-LAST-EXTERNAL"
    assert (str(first.open), str(first.high), str(first.low), str(first.close)) == (
        "93425.2",
        "93452.0",
        "93392.0",
        "93452.0",
    )
    assert str(first.volume) == "42.5844"
    assert first.ts_event == DAY_NANOS + MINUTE_NANOS - 1


@pytest.mark.integration
def test_a_day_of_coinbase_intx_klines_is_downloaded(tmp_path: Path) -> None:
    with coinbase_intx_replay() as coinbase:
        assert downloaded(coinbase, BTC_PERP, tmp_path) == [Outcome.FETCHED] * 2
        instrument = snapshot_instrument(coinbase, BTC_PERP, tmp_path)
        candles = tmp_path / coinbase.day_file(BTC_PERP, Bar, DAY).path

        stamps = [each.ts_event for each in coinbase.parse(candles, Bar, instrument)]

    # Coinbase sends no candle for a minute without a trade.
    assert len(stamps) == 1398
    assert stamps == sorted(set(stamps))
    assert stamps[0] > DAY_NANOS
    assert stamps[-1] == DAY_NANOS + 1440 * MINUTE_NANOS - 1


@pytest.mark.unit
@pytest.mark.parametrize("symbol", ["BTC-PERP", "ETH-PERP"])
def test_coinbase_intx_perpetual_instrument_gives_the_volume_unit(
    tmp_path: Path, symbol: str
) -> None:
    with coinbase_intx_replay() as coinbase:
        assert coinbase.symbol(coinbase.instrument_id(symbol)) == symbol

        instrument = snapshot_instrument(coinbase, symbol, tmp_path)

    assert isinstance(instrument, CryptoPerpetual)
    assert not instrument.is_inverse
    assert str(instrument.base_currency) == symbol.removesuffix("-PERP")
    assert str(instrument.quote_currency) == "USDC"
    assert str(instrument.multiplier) == "1.0"
    assert str(instrument.size_increment) == "0.0001"


@pytest.mark.unit
def test_an_unlisted_coinbase_intx_symbol_is_missing_at_the_source() -> None:
    with coinbase_intx_replay() as coinbase:
        raw = coinbase.day_file("NOPE-PERP", Bar, DAY)
        assert callable(raw.origin)
        with pytest.raises(MissingAtSourceError, match="NOPE-PERP"):
            asyncio.run(raw.origin())
