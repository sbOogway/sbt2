import re
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model import Bar, FundingRateUpdate, TradeTick
from served_source import INSTRUMENT_ID, SYMBOL, ServedSource, spot_pair

from sbt2.assets import Calendar
from sbt2.data import (
    Catalog,
    DayRange,
    DownloadOptions,
    DownloadRequest,
    IngestOptions,
    IngestRequest,
    Window,
    download,
    ingest,
)
from sbt2.data.sources import Gap, UnsupportedDataTypeError
from sbt2.run import (
    DataFolders,
    InstrumentAssetClassError,
    LiquidationWithoutQuotesError,
    MissingDataError,
    SnapshotBufferError,
    preflight,
)
from sbt2.spec import ResolvedRunSpec, load

VENUES = """
[test_linear]
name = "BYBIT"
source = "served"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
"""
DAY = date(2024, 1, 1)
NEXT_DAY = date(2024, 1, 2)
# 1,000,000 seconds after the test part's start, the most 1s snapshots
# nautilus keeps.
LAST_SNAPSHOT = "2024-01-12T13:46:40"
TEST_FROM_DAY = "{ validation_start = 2023-12-31, test_start = 2024-01-01 }"


def spec(tmp_path: Path, **values: Any) -> ResolvedRunSpec:
    lines = {
        "strategy": '"run_strategies:BuyThenSell"',
        "instruments": '["BTCUSDT-LINEAR.BYBIT"]',
        "period": "[2024-01-01T02:00:00, 2024-01-05]",
        "split": "{ validation_start = 2024-01-03, test_start = 2024-01-04 }",
        "part": '"train"',
        "venue": '"test_linear"',
        "capital": '"10000 USDT"',
        **values,
    }
    path, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    path.write_text("".join(f"{key} = {value}\n" for key, value in lines.items()))
    venues.write_text(VENUES)
    [spec] = load(path, venue_profiles=venues)
    return spec


@dataclass(frozen=True)
class Weekdays:
    every_day: Calendar

    def trading_days(self, start: datetime, end: datetime) -> list[date]:
        days = self.every_day.trading_days(start, end)
        return [each for each in days if each.weekday() < 5]


def midnight(day: date) -> datetime:
    return datetime.combine(day, time(), UTC)


@pytest.fixture
def folders(tmp_path: Path) -> DataFolders:
    return DataFolders(raw=tmp_path / "raw", catalog=tmp_path / "catalog")


def stock(source: ServedSource, folders: DataFolders, first: date, last: date) -> None:
    """Ingest the source's days into the catalog, then forget what it fetched."""
    days = DayRange((SYMBOL,), first, last)
    download(source, DownloadRequest(days), DownloadOptions(folders.raw))
    ingest(
        source,
        IngestRequest(days),
        IngestOptions(folders.raw, folders.catalog),
    )
    source.fetched.clear()


@pytest.mark.integration
def test_a_covered_run_passes_without_fetching(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    stock(source, folders, DAY, NEXT_DAY)

    assert preflight(spec(tmp_path), source, folders) == ()
    assert source.fetched == []


@pytest.mark.integration
def test_missing_days_are_fetched_and_ingested_before_the_check(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    stock(source, folders, DAY, DAY)

    assert preflight(spec(tmp_path), source, folders) == ()
    next_day = Window(midnight(NEXT_DAY), midnight(date(2024, 1, 3)))
    assert len(Catalog(folders.catalog).frame(INSTRUMENT_ID, TradeTick, next_day)) == 24


@pytest.mark.integration
def test_an_empty_catalog_is_filled_from_the_source(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)

    assert preflight(spec(tmp_path), source, folders) == ()


@pytest.mark.integration
def test_a_candle_run_fetches_its_missing_candle_days(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)

    assert preflight(spec(tmp_path, bars='"candles"'), source, folders) == ()
    days = {each.parent.name for each in source.fetched if each.suffix == ".json"}
    assert days == {"Bar", "MarkPriceUpdate", "FundingRateUpdate"}
    window = Window(midnight(DAY), midnight(date(2024, 1, 3)))
    assert len(Catalog(folders.catalog).frame(INSTRUMENT_ID, Bar, window)) == 48


@pytest.mark.integration
def test_days_still_missing_after_the_fetch_fail_naming_each(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    source.withdraw(TradeTick, NEXT_DAY)
    stock(source, folders, DAY, NEXT_DAY)

    with pytest.raises(
        MissingDataError, match=re.escape("BTCUSDT-LINEAR.BYBIT TradeTick 2024-01-02")
    ):
        preflight(spec(tmp_path), source, folders)
    assert source.day_file(SYMBOL, TradeTick, NEXT_DAY).path in source.fetched


@pytest.mark.integration
def test_the_warmup_days_are_checked_too(tmp_path: Path, folders: DataFolders) -> None:
    source = ServedSource()
    source.serve(DAY, date(2024, 1, 3))
    source.withdraw(TradeTick, DAY)
    stock(source, folders, DAY, date(2024, 1, 3))
    run = spec(
        tmp_path,
        period="[2024-01-02T01:00:00, 2024-01-06]",
        split="{ validation_start = 2024-01-04, test_start = 2024-01-05 }",
    )

    with pytest.raises(MissingDataError, match="TradeTick 2024-01-01"):
        preflight(run, source, folders)


@pytest.mark.integration
def test_known_gap_days_pass_and_are_returned(
    tmp_path: Path, folders: DataFolders
) -> None:
    gap = Gap(INSTRUMENT_ID, FundingRateUpdate, NEXT_DAY)
    source = ServedSource(known_gaps=frozenset({gap}))
    source.serve(DAY, NEXT_DAY)
    source.withdraw(FundingRateUpdate, NEXT_DAY)
    stock(source, folders, DAY, NEXT_DAY)

    assert preflight(spec(tmp_path), source, folders) == (gap,)
    assert source.fetched == []


@pytest.mark.integration
def test_days_the_calendar_closes_are_not_required(
    tmp_path: Path, folders: DataFolders
) -> None:
    friday = date(2024, 1, 5)
    source = ServedSource()
    source.serve(friday, friday)
    stock(source, folders, friday, friday)
    run = spec(
        tmp_path,
        period="[2024-01-05T02:00:00, 2024-01-10]",
        split="{ validation_start = 2024-01-08, test_start = 2024-01-09 }",
    )
    weekdays = replace(run.asset, calendar=Weekdays(run.asset.calendar))

    assert preflight(replace(run, asset=weekdays), source, folders) == ()


@pytest.mark.integration
def test_an_instrument_the_source_lacks_fails_as_missing_data(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve_days(DAY, NEXT_DAY)

    with pytest.raises(MissingDataError, match=re.escape("BTCUSDT-LINEAR.BYBIT")):
        preflight(spec(tmp_path), source, folders)


@pytest.mark.integration
def test_an_instrument_of_another_asset_class_fails(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY, spot_pair())

    with pytest.raises(
        InstrumentAssetClassError,
        match=r"BTCUSDT-LINEAR.BYBIT is CRYPTOCURRENCY/SPOT, not .* CRYPTOCURRENCY/SWAP",
    ):
        preflight(spec(tmp_path), source, folders)


@pytest.mark.integration
def test_a_segment_over_the_snapshot_buffer_fails_before_fetching(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, date(2024, 1, 12))
    run = spec(
        tmp_path,
        period="[2023-12-30, 2024-01-12T13:46:41]",
        split=TEST_FROM_DAY,
        part='"test"',
        equity_interval='"1s"',
    )

    with pytest.raises(SnapshotBufferError, match="1,000,001"):
        preflight(run, source, folders)
    assert source.fetched == []


@pytest.mark.integration
def test_a_segment_filling_the_snapshot_buffer_exactly_passes(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(date(2023, 12, 31), date(2024, 1, 12))
    stock(source, folders, date(2023, 12, 31), date(2024, 1, 12))
    run = spec(
        tmp_path,
        period=f"[2023-12-30, {LAST_SNAPSHOT}]",
        split=TEST_FROM_DAY,
        part='"test"',
        equity_interval='"1s"',
    )

    assert preflight(run, source, folders) == ()


@pytest.mark.integration
def test_liquidation_on_a_run_without_quotes_fails_before_fetching(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    run = spec(tmp_path, liquidation="true")

    with pytest.raises(LiquidationWithoutQuotesError, match="only on quotes"):
        preflight(run, source, folders)
    assert source.fetched == []


@pytest.mark.integration
def test_liquidation_on_a_run_streaming_quotes_passes_the_guard(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    run = spec(
        tmp_path, strategy='"run_strategies:HoldOnQuoteBars"', liquidation="true"
    )

    with pytest.raises(UnsupportedDataTypeError, match="no QuoteTick"):
        preflight(run, source, folders)
