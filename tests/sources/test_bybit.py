from datetime import date
from pathlib import Path, PurePosixPath

import pytest
from nautilus_trader.model import InstrumentId, OrderBookDelta, TradeTick

from sbt2.sources import RawFile, Source, UnsupportedDataTypeError, source

REPO_CONFIG = Path(__file__).parents[2] / "config" / "sources.toml"
DAY = date(2025, 1, 1)


@pytest.fixture
def bybit() -> Source:
    return source("bybit", REPO_CONFIG)


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
