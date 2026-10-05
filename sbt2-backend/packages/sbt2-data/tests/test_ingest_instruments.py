from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from local_source import (
    CANDLE_TYPE,
    INSTRUMENT_ID,
    SYMBOL,
    LocalSource,
    RawFolder,
    start_of,
    write_snapshot,
)
from nautilus_trader.model import Bar, MarkPriceUpdate, NautilusDataType, TradeTick
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.data import (
    DayRange,
    DayResult,
    IngestOptions,
    IngestRequest,
    InstrumentChangedError,
    NoSnapshotError,
    Tally,
    ingest,
)

DAY = date(2024, 1, 1)
LATER = DAY + timedelta(days=30)
HOUR = 3_600_000_000_000


TRADES_OF_DAY = DayRange((SYMBOL,), DAY, DAY, ("TradeTick",))
ONE_DAY = IngestRequest(TRADES_OF_DAY)
REINGEST = IngestRequest(TRADES_OF_DAY, reingest=True)


def run(raw: Path, catalog: Path, request: IngestRequest = ONE_DAY) -> Tally[DayResult]:
    return ingest(LocalSource(), request, IngestOptions(raw, catalog))


def stored_instruments(catalog: Path) -> list[Any]:
    return ParquetDataCatalog(str(catalog)).instruments(
        instrument_ids=[str(INSTRUMENT_ID)]
    )


def trade_days(catalog: Path) -> list[tuple[int, int]]:
    return ParquetDataCatalog(str(catalog)).get_intervals(
        NautilusDataType.TradeTick, str(INSTRUMENT_ID)
    )


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    path = tmp_path / "raw"
    write_snapshot(path, DAY)
    RawFolder(path).write_day(TradeTick, DAY, [start_of(DAY) + HOUR])
    return path


@pytest.fixture
def catalog(tmp_path: Path, raw: Path) -> Path:
    path = tmp_path / "catalog"
    run(raw, path)
    return path


@pytest.mark.unit
def test_the_instrument_comes_from_the_snapshot_initialised_on_its_day(
    catalog: Path,
) -> None:
    [instrument] = stored_instruments(catalog)

    assert instrument.ts_init == start_of(DAY)


@pytest.mark.unit
def test_the_newest_snapshot_is_the_one_ingested(tmp_path: Path, raw: Path) -> None:
    write_snapshot(raw, LATER, margin_init="0.02")
    catalog = tmp_path / "catalog"

    run(raw, catalog)

    [instrument] = stored_instruments(catalog)
    assert instrument.ts_init == start_of(LATER)
    assert str(instrument.margin_init) == "0.02"


@pytest.mark.unit
def test_a_newer_snapshot_with_the_same_spec_keeps_the_catalogs(
    raw: Path, catalog: Path
) -> None:
    write_snapshot(raw, LATER)

    run(raw, catalog)

    [instrument] = stored_instruments(catalog)
    assert instrument.ts_init == start_of(DAY)


@pytest.mark.unit
def test_a_newer_snapshot_that_differs_fails_loudly(raw: Path, catalog: Path) -> None:
    write_snapshot(raw, LATER, margin_init="0.02")

    with pytest.raises(InstrumentChangedError, match="re-ingest"):
        run(raw, catalog)

    [instrument] = stored_instruments(catalog)
    assert instrument.ts_init == start_of(DAY)


@pytest.mark.unit
def test_reingest_replaces_the_instrument_and_rebuilds_its_days(
    raw: Path, catalog: Path
) -> None:
    write_snapshot(raw, LATER, margin_init="0.02")
    RawFolder(raw).write_day(TradeTick, DAY, [start_of(DAY) + 2 * HOUR])

    run(raw, catalog, REINGEST)

    [instrument] = stored_instruments(catalog)
    assert instrument.ts_init == start_of(LATER)
    trades = ParquetDataCatalog(str(catalog)).query(NautilusDataType.TradeTick)
    assert [each.ts_event for each in trades] == [start_of(DAY) + 2 * HOUR]


@pytest.mark.unit
def test_reingest_removes_days_outside_the_requested_range(
    raw: Path, catalog: Path
) -> None:
    other_day = DAY + timedelta(days=1)
    RawFolder(raw).write_day(TradeTick, other_day, [start_of(other_day)])
    run(
        raw, catalog, IngestRequest(DayRange((SYMBOL,), DAY, other_day, ("TradeTick",)))
    )
    write_snapshot(raw, LATER, margin_init="0.02")

    run(raw, catalog, REINGEST)

    assert trade_days(catalog) == [(start_of(DAY), start_of(other_day) - 1)]


@pytest.mark.unit
def test_a_symbol_without_a_snapshot_is_refused(tmp_path: Path) -> None:
    with pytest.raises(NoSnapshotError, match=SYMBOL):
        run(tmp_path / "raw", tmp_path / "catalog")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("data_type", "identifier"),
    [(MarkPriceUpdate, INSTRUMENT_ID), (Bar, CANDLE_TYPE)],
    ids=["mark_prices", "candles"],
)
def test_reingest_removes_every_data_type_of_the_instrument(
    raw: Path, catalog: Path, data_type: type, identifier: object
) -> None:
    name = data_type.__name__
    RawFolder(raw).write_day(data_type, DAY, [start_of(DAY)])
    run(raw, catalog, IngestRequest(DayRange((SYMBOL,), DAY, DAY, (name,))))
    write_snapshot(raw, LATER, margin_init="0.02")

    run(raw, catalog, REINGEST)

    assert (
        ParquetDataCatalog(str(catalog)).get_intervals(
            getattr(NautilusDataType, name), str(identifier)
        )
        == []
    )
