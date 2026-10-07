"""Downloads a real day from Bybit and parses it; run with ``pytest -m live``."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from nautilus_trader.model import Bar, FundingRateUpdate, MarkPriceUpdate, TradeTick

from sbt2.data import DayRange, DownloadOptions, DownloadRequest, Outcome, download
from sbt2.data.sources import Source, source

DAY = date(2025, 1, 1)
DAY_START = pd.Timestamp(DAY, tz="UTC").value
DAY_END = DAY_START + pd.Timedelta(days=1).value
MINUTE = pd.Timedelta(minutes=1).value
HOUR = pd.Timedelta(hours=1).value


@pytest.fixture(scope="module")
def raw(tmp_path_factory: pytest.TempPathFactory) -> tuple[Source, Path]:
    root = tmp_path_factory.mktemp("raw")
    bybit = source("bybit", root / "known_gaps.toml")
    tally = download(
        bybit, DownloadRequest(DayRange(("BTCUSDT",), DAY, DAY)), DownloadOptions(root)
    )
    assert tally.results
    assert {each.outcome for each in tally.results} == {Outcome.FETCHED}, tally
    return bybit, root


def day_file(raw: tuple[Source, Path], data_type: type) -> Path:
    bybit, root = raw
    return root / bybit.day_file("BTCUSDT", data_type, DAY).path


def instrument(raw: tuple[Source, Path]) -> Any:
    bybit, root = raw
    today = datetime.now(UTC).date()
    snapshot = root / bybit.instrument_snapshot("BTCUSDT", today).path
    (instrument,) = bybit.parse_instruments(snapshot).values()
    return instrument


@pytest.mark.live
@pytest.mark.integration
def test_the_instrument_snapshot_is_btcusdt(raw: tuple[Source, Path]) -> None:
    assert str(instrument(raw).id) == "BTCUSDT-LINEAR.BYBIT"


@pytest.mark.live
@pytest.mark.integration
def test_the_trades_dump_parses_into_the_days_trades(raw: tuple[Source, Path]) -> None:
    bybit, _ = raw
    stamps = [
        each.ts_event
        for each in bybit.parse(day_file(raw, TradeTick), TradeTick, instrument(raw))
    ]

    assert len(stamps) > 100_000
    assert stamps[0] >= DAY_START
    assert stamps[-1] < DAY_END
    assert stamps == sorted(stamps)


@pytest.mark.live
@pytest.mark.integration
def test_funding_settles_every_eight_hours(raw: tuple[Source, Path]) -> None:
    bybit, _ = raw
    records = bybit.parse(
        day_file(raw, FundingRateUpdate), FundingRateUpdate, instrument(raw)
    )

    assert [each.ts_event for each in records] == [
        DAY_START + hours * HOUR for hours in (0, 8, 16)
    ]


@pytest.mark.live
@pytest.mark.integration
def test_mark_price_covers_every_minute(raw: tuple[Source, Path]) -> None:
    bybit, _ = raw
    records = bybit.parse(
        day_file(raw, MarkPriceUpdate), MarkPriceUpdate, instrument(raw)
    )

    assert [each.ts_event for each in records] == [
        DAY_START + MINUTE * n - 1 for n in range(1, 1441)
    ]


@pytest.mark.live
@pytest.mark.integration
def test_candles_cover_every_minute(raw: tuple[Source, Path]) -> None:
    bybit, _ = raw
    records = bybit.parse(day_file(raw, Bar), Bar, instrument(raw))

    assert [each.ts_event for each in records] == [
        DAY_START + MINUTE * n - 1 for n in range(1, 1441)
    ]
