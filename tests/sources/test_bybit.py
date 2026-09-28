import asyncio
import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
from bybit_replay import bybit_replay
from nautilus_trader.model import (
    CryptoPerpetual,
    InstrumentId,
    OrderBookDelta,
    TradeTick,
)

from sbt2.sources import (
    MissingAtSourceError,
    RawFile,
    Source,
    UnsupportedDataTypeError,
    source,
)
from sbt2.sources.bybit import BybitSource, Endpoints

REPO_CONFIG = Path(__file__).parents[2] / "config" / "sources.toml"
DAY = date(2025, 1, 1)


@pytest.fixture
def bybit() -> Source:
    return source("bybit", REPO_CONFIG)


@pytest.fixture
def replayed() -> Iterator[Source]:
    with bybit_replay() as api:
        yield BybitSource(frozenset(), Endpoints(api=api))


def fetched(raw: RawFile) -> Any:
    assert callable(raw.origin)
    return json.loads(asyncio.run(raw.origin()))


def test_instrument_ids_are_linear_bybit_ids(bybit: Source) -> None:
    assert bybit.instrument_id("BTCUSDT") == InstrumentId.from_str(
        "BTCUSDT-LINEAR.BYBIT"
    )


def test_trades_come_from_the_daily_public_dump(bybit: Source) -> None:
    assert bybit.day_file("BTCUSDT", TradeTick, DAY) == RawFile(
        PurePosixPath("bybit/linear/BTCUSDT/trading/BTCUSDT2025-01-01.csv.gz"),
        "https://public.bybit.com/trading/BTCUSDT/BTCUSDT2025-01-01.csv.gz",
    )


def test_unserved_data_type_is_refused(bybit: Source) -> None:
    with pytest.raises(UnsupportedDataTypeError):
        bybit.day_file("BTCUSDT", OrderBookDelta, DAY)


def test_instrument_snapshot_is_saved_under_the_day_it_is_taken(
    bybit: Source,
) -> None:
    assert bybit.instrument_snapshot("BTCUSDT", date(2026, 9, 28)).path == (
        PurePosixPath("bybit/linear/BTCUSDT/instrument/BTCUSDT2026-09-28.json")
    )


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


def test_unlisted_symbol_is_missing_at_the_source(replayed: Source) -> None:
    with pytest.raises(MissingAtSourceError, match="NOPEUSDT"):
        fetched(replayed.instrument_snapshot("NOPEUSDT", DAY))
