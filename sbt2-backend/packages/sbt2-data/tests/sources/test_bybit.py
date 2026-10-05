import asyncio
import json
import re
from collections.abc import Callable
from datetime import date
from pathlib import PurePosixPath
from typing import Any

import pandas as pd
import pytest
from nautilus_trader.model import (
    Bar,
    CryptoPerpetual,
    FundingRateUpdate,
    InstrumentId,
    MarkPriceUpdate,
    OrderBookDelta,
    TradeTick,
)

from sbt2.data.sources import (
    MissingAtSourceError,
    RawFile,
    Source,
    UnsupportedDataTypeError,
)

DAY = date(2025, 1, 1)


def fetched(raw: RawFile) -> Any:
    assert callable(raw.origin)
    return json.loads(asyncio.run(raw.origin()))


@pytest.mark.unit
def test_instrument_ids_are_linear_bybit_ids(bybit: Source) -> None:
    assert bybit.instrument_id("BTCUSDT") == InstrumentId.from_str(
        "BTCUSDT-LINEAR.BYBIT"
    )


@pytest.mark.unit
def test_the_symbol_of_an_instrument_id_is_its_bybit_symbol(bybit: Source) -> None:
    assert bybit.symbol(InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")) == "BTCUSDT"


@pytest.mark.unit
def test_an_instrument_id_of_another_venue_has_no_bybit_symbol(bybit: Source) -> None:
    with pytest.raises(ValueError, match=re.escape("BTCUSDT-PERP.BINANCE")):
        bybit.symbol(InstrumentId.from_str("BTCUSDT-PERP.BINANCE"))


@pytest.mark.unit
def test_trades_come_from_the_daily_public_dump(bybit: Source) -> None:
    assert bybit.day_file("BTCUSDT", TradeTick, DAY) == RawFile(
        PurePosixPath("bybit/linear/BTCUSDT/trading/BTCUSDT2025-01-01.csv.gz"),
        "https://public.bybit.com/trading/BTCUSDT/BTCUSDT2025-01-01.csv.gz",
    )


@pytest.mark.unit
def test_serves_trades_funding_mark_prices_and_candles_per_day(bybit: Source) -> None:
    assert bybit.data_types == (TradeTick, FundingRateUpdate, MarkPriceUpdate, Bar)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("data_type", "path"),
    [
        (FundingRateUpdate, "bybit/linear/BTCUSDT/funding/BTCUSDT2025-01-01.json"),
        (MarkPriceUpdate, "bybit/linear/BTCUSDT/mark_price/BTCUSDT2025-01-01.json"),
        (Bar, "bybit/linear/BTCUSDT/candles/BTCUSDT2025-01-01.json"),
    ],
)
def test_rest_data_is_saved_one_json_file_per_day(
    bybit: Source, data_type: type, path: str
) -> None:
    assert bybit.day_file("BTCUSDT", data_type, DAY).path == PurePosixPath(path)


@pytest.mark.unit
def test_unserved_data_type_is_refused(bybit: Source) -> None:
    with pytest.raises(UnsupportedDataTypeError):
        bybit.day_file("BTCUSDT", OrderBookDelta, DAY)


@pytest.mark.unit
def test_instrument_snapshot_is_saved_under_the_day_it_is_taken(
    bybit: Source,
) -> None:
    assert bybit.instrument_snapshot("BTCUSDT", date(2026, 9, 28)).path == (
        PurePosixPath("bybit/linear/BTCUSDT/instrument/BTCUSDT2026-09-28.json")
    )


@pytest.mark.unit
def test_instrument_snapshot_takes_margin_from_the_lowest_risk_tier(
    replayed: Source,
) -> None:
    spec = fetched(replayed.instrument_snapshot("BTCUSDT", DAY))

    instrument = CryptoPerpetual.from_dict(spec)
    assert instrument.id == InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")
    assert (str(instrument.margin_init), str(instrument.margin_maint)) == (
        "0.0066",
        "0.0033",
    )


@pytest.mark.unit
def test_instrument_snapshot_keeps_the_funding_interval_in_minutes(
    replayed: Source,
) -> None:
    spec = fetched(replayed.instrument_snapshot("BTCUSDT", DAY))

    assert CryptoPerpetual.from_dict(spec).info == {"fundingInterval": 480}


@pytest.mark.unit
def test_funding_is_the_days_settlements_as_returned(replayed: Source) -> None:
    rates = fetched(replayed.day_file("BTCUSDT", FundingRateUpdate, DAY))

    assert [pd.Timestamp(each["ts_event"], tz="UTC").hour for each in rates] == [
        0,
        8,
        16,
    ]
    assert [each.get("interval") for each in rates] == [None, 480, 480]


@pytest.mark.unit
def test_mark_prices_are_every_minute_of_the_day(replayed: Source) -> None:
    pages = fetched(replayed.day_file("BTCUSDT", MarkPriceUpdate, DAY))

    opens = sorted(int(kline[0]) for page in pages for kline in page["result"]["list"])
    day = pd.date_range(DAY, periods=1440, freq="min", tz="UTC")
    assert opens == [each.value // 1_000_000 for each in day]


@pytest.mark.unit
def test_candles_are_every_minute_of_the_day(replayed: Source) -> None:
    bars = fetched(replayed.day_file("BTCUSDT", Bar, DAY))

    closes = pd.date_range(DAY, periods=1440, freq="min", tz="UTC") + pd.Timedelta(
        minutes=1
    )
    assert [each["ts_event"] for each in bars] == [each.value for each in closes]
    assert {each["bar_type"] for each in bars} == {
        "BTCUSDT-LINEAR.BYBIT-1-MINUTE-LAST-EXTERNAL"
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw_file",
    [
        lambda bybit: bybit.instrument_snapshot("NOPEUSDT", DAY),
        lambda bybit: bybit.day_file("NOPEUSDT", FundingRateUpdate, DAY),
        lambda bybit: bybit.day_file("NOPEUSDT", MarkPriceUpdate, DAY),
        lambda bybit: bybit.day_file("NOPEUSDT", Bar, DAY),
    ],
    ids=["instrument", "funding", "mark_price", "candles"],
)
def test_unlisted_symbol_is_missing_at_the_source(
    replayed: Source, raw_file: Callable[[Source], RawFile]
) -> None:
    with pytest.raises(MissingAtSourceError, match="NOPEUSDT"):
        fetched(raw_file(replayed))
