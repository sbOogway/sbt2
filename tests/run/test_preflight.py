from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model import FundingRateUpdate, TradeTick
from served_source import INSTRUMENT_ID, SYMBOL, ServedSource, spot_pair

from sbt2.assets import Calendar
from sbt2.data import (
    Catalog,
    DownloadOptions,
    DownloadRequest,
    IngestOptions,
    IngestRequest,
    Window,
    download,
    ingest,
)
from sbt2.run import (
    DataFolders,
    InstrumentAssetClassError,
    LiquidationWithoutQuotesError,
    MissingDataError,
    SnapshotBufferError,
    preflight,
)
from sbt2.sources import Gap, UnsupportedDataTypeError
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
# 1,000,000 seconds after the start, the most 1s snapshots nautilus keeps.
LAST_SNAPSHOT = "2024-01-12T15:46:40"


def spec(tmp_path: Path, **values: Any) -> ResolvedRunSpec:
    lines = {
        "strategy": '"run_strategies:BuyThenSell"',
        "instruments": '["BTCUSDT-LINEAR.BYBIT"]',
        "start": "2024-01-01T02:00:00",
        "end": "2024-01-03",
        "venue": '"test_linear"',
        "capital": '"10000 USDT"',
        **values,
    }
    path, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    path.write_text("".join(f"{key} = {value}\n" for key, value in lines.items()))
    venues.write_text(VENUES)
    return load(path, venue_profiles=venues)


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
    symbols = (SYMBOL,)
    download(
        source, DownloadRequest(symbols, first, last), DownloadOptions(folders.raw)
    )
    ingest(
        source,
        IngestRequest(symbols, first, last),
        IngestOptions(folders.raw, folders.catalog),
    )
    source.fetched.clear()


def test_a_covered_run_passes_without_fetching(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    stock(source, folders, DAY, NEXT_DAY)

    assert preflight(spec(tmp_path), source, folders) == ()
    assert source.fetched == []


def test_missing_days_are_fetched_and_ingested_before_the_check(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    stock(source, folders, DAY, DAY)

    assert preflight(spec(tmp_path), source, folders) == ()
    next_day = Window(midnight(NEXT_DAY), midnight(date(2024, 1, 3)))
    assert len(Catalog(folders.catalog).trades(INSTRUMENT_ID, next_day)) == 24


def test_an_empty_catalog_is_filled_from_the_source(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)

    assert preflight(spec(tmp_path), source, folders) == ()


def test_days_still_missing_after_the_fetch_fail_naming_each(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    source.withdraw(TradeTick, NEXT_DAY)
    stock(source, folders, DAY, NEXT_DAY)

    with pytest.raises(
        MissingDataError, match="BTCUSDT-LINEAR.BYBIT TradeTick 2024-01-02"
    ):
        preflight(spec(tmp_path), source, folders)
    assert source.day_file(SYMBOL, TradeTick, NEXT_DAY).path in source.fetched


def test_the_warmup_days_are_checked_too(tmp_path: Path, folders: DataFolders) -> None:
    source = ServedSource()
    source.serve(DAY, date(2024, 1, 3))
    source.withdraw(TradeTick, DAY)
    stock(source, folders, DAY, date(2024, 1, 3))
    run = spec(tmp_path, start="2024-01-02T01:00:00", end="2024-01-04")

    with pytest.raises(MissingDataError, match="TradeTick 2024-01-01"):
        preflight(run, source, folders)


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


def test_days_the_calendar_closes_are_not_required(
    tmp_path: Path, folders: DataFolders
) -> None:
    friday = date(2024, 1, 5)
    source = ServedSource()
    source.serve(friday, friday)
    stock(source, folders, friday, friday)
    run = spec(tmp_path, start="2024-01-05T02:00:00", end="2024-01-08")
    weekdays = replace(run.asset, calendar=Weekdays(run.asset.calendar))

    assert preflight(replace(run, asset=weekdays), source, folders) == ()


def test_an_instrument_the_source_lacks_fails_as_missing_data(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve_days(DAY, NEXT_DAY)

    with pytest.raises(MissingDataError, match="BTCUSDT-LINEAR.BYBIT"):
        preflight(spec(tmp_path), source, folders)


def test_an_instrument_of_another_asset_class_fails(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY, spot_pair())

    with pytest.raises(
        InstrumentAssetClassError,
        match="BTCUSDT-LINEAR.BYBIT is CRYPTOCURRENCY/SPOT, not .* CRYPTOCURRENCY/SWAP",
    ):
        preflight(spec(tmp_path), source, folders)


def test_a_segment_over_the_snapshot_buffer_fails_before_fetching(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, date(2024, 1, 12))
    run = spec(tmp_path, end="2024-01-12T15:46:41", equity_interval='"1s"')

    with pytest.raises(SnapshotBufferError, match="1,000,001"):
        preflight(run, source, folders)
    assert source.fetched == []


def test_a_segment_filling_the_snapshot_buffer_exactly_passes(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, date(2024, 1, 12))
    stock(source, folders, DAY, date(2024, 1, 12))
    run = spec(tmp_path, end=LAST_SNAPSHOT, equity_interval='"1s"')

    assert preflight(run, source, folders) == ()


def test_liquidation_on_a_run_without_quotes_fails_before_fetching(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    run = spec(tmp_path, liquidation="true")

    with pytest.raises(LiquidationWithoutQuotesError, match="only on quotes"):
        preflight(run, source, folders)
    assert source.fetched == []


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
