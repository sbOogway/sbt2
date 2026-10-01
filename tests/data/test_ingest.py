from datetime import date, timedelta
from pathlib import Path

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
from nautilus_trader.model import (
    Bar,
    FundingRateUpdate,
    MarkPriceUpdate,
    NautilusDataType,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.data import (
    DayRange,
    DayResult,
    IngestOptions,
    IngestOutcome,
    IngestRequest,
    OutsideDayError,
    Tally,
    ingest,
)
from sbt2.data.sources import Gap, UnsupportedDataTypeError

DAY = date(2024, 1, 1)
NEXT_DAY = DAY + timedelta(days=1)
HOUR = 3_600_000_000_000
DAY_NANOS = 24 * HOUR
TRADES = NautilusDataType.TradeTick


class Recorder:
    def __init__(self) -> None:
        self.days = 0
        self.results: list[DayResult] = []

    def planned(self, days: int) -> None:
        self.days = days

    def finished(self, result: DayResult) -> None:
        self.results.append(result)


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    path = tmp_path / "raw"
    write_snapshot(path, DAY)
    return path


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    return tmp_path / "catalog"


def request(end: date = DAY, *data: str) -> IngestRequest:
    return IngestRequest(DayRange((SYMBOL,), DAY, end, data))


def run(
    raw: Path,
    catalog: Path,
    ingest_request: IngestRequest,
    source: LocalSource | None = None,
) -> Tally[DayResult]:
    return ingest(source or LocalSource(), ingest_request, IngestOptions(raw, catalog))


def hourly(day: date) -> list[int]:
    return list(range(start_of(day), start_of(day) + DAY_NANOS, HOUR))


def bounds(day: date) -> tuple[int, int]:
    return start_of(day), start_of(day) + DAY_NANOS - 1


def outcomes(tally: Tally[DayResult]) -> dict[tuple[str, date], IngestOutcome]:
    return {(each.day.data, each.day.day): each.outcome for each in tally.results}


def intervals(catalog: Path, data_type: NautilusDataType) -> list[tuple[int, int]]:
    return ParquetDataCatalog(str(catalog)).get_intervals(data_type, str(INSTRUMENT_ID))


@pytest.mark.unit
def test_each_day_is_one_file_named_with_the_whole_days_bounds(
    raw: Path, catalog_path: Path
) -> None:
    for day in (DAY, NEXT_DAY):
        RawFolder(raw).write_day(TradeTick, day, hourly(day)[3:5])

    run(raw, catalog_path, request(NEXT_DAY, "TradeTick"))

    assert intervals(catalog_path, TRADES) == [bounds(DAY), bounds(NEXT_DAY)]
    trades = ParquetDataCatalog(str(catalog_path)).query(TRADES)
    assert [each.ts_event for each in trades] == hourly(DAY)[3:5] + hourly(NEXT_DAY)[
        3:5
    ]


@pytest.mark.unit
def test_every_served_data_type_is_ingested_by_default(
    raw: Path, catalog_path: Path
) -> None:
    RawFolder(raw).write_day(TradeTick, DAY, hourly(DAY))
    RawFolder(raw).write_day(MarkPriceUpdate, DAY, hourly(DAY))
    RawFolder(raw).write_day(FundingRateUpdate, DAY, [start_of(DAY) + 8 * HOUR])
    RawFolder(raw).write_day(Bar, DAY, hourly(DAY))

    tally = run(raw, catalog_path, request())

    assert set(outcomes(tally).values()) == {IngestOutcome.WRITTEN}
    for data_type in (TRADES, NautilusDataType.MarkPriceUpdate):
        assert intervals(catalog_path, data_type) == [bounds(DAY)]
    assert ParquetDataCatalog(str(catalog_path)).get_intervals(
        NautilusDataType.Bar, str(CANDLE_TYPE)
    ) == [bounds(DAY)]
    fundings = ParquetDataCatalog(str(catalog_path)).query(
        NautilusDataType.FundingRateUpdate
    )
    assert [(each.ts_event, each.interval) for each in fundings] == [
        (start_of(DAY) + 8 * HOUR, 480)
    ]


@pytest.mark.unit
@pytest.mark.parametrize("data_type", [TradeTick, MarkPriceUpdate, FundingRateUpdate])
def test_a_raw_file_without_rows_becomes_a_covered_empty_day(
    raw: Path, catalog_path: Path, data_type: type
) -> None:
    name = data_type.__name__
    RawFolder(raw).write_day(data_type, DAY, [])

    tally = run(raw, catalog_path, request(DAY, name))

    assert outcomes(tally) == {(name, DAY): IngestOutcome.EMPTY}
    stored = getattr(NautilusDataType, name)
    assert intervals(catalog_path, stored) == [bounds(DAY)]
    assert ParquetDataCatalog(str(catalog_path)).query(stored) == []


@pytest.mark.unit
def test_candles_are_written_under_their_bar_type_with_the_whole_days_bounds(
    raw: Path, catalog_path: Path
) -> None:
    RawFolder(raw).write_day(Bar, DAY, hourly(DAY)[:2])

    run(raw, catalog_path, request(DAY, "Bar"))

    folder = catalog_path / "data" / "bars" / str(CANDLE_TYPE)
    assert [each.name for each in folder.iterdir()] == [
        "2024-01-01T00-00-00-000000000Z_2024-01-01T23-59-59-999999999Z.parquet"
    ]
    bars = ParquetDataCatalog(str(catalog_path)).query(
        NautilusDataType.Bar, [str(CANDLE_TYPE)]
    )
    assert [(each.bar_type, each.ts_event) for each in bars] == [
        (CANDLE_TYPE, ts) for ts in hourly(DAY)[:2]
    ]


@pytest.mark.unit
def test_a_day_without_candles_is_a_covered_empty_bar_file(
    raw: Path, catalog_path: Path
) -> None:
    RawFolder(raw).write_day(Bar, DAY, [])

    tally = run(raw, catalog_path, request(DAY, "Bar"))

    assert outcomes(tally) == {("Bar", DAY): IngestOutcome.EMPTY}
    catalog = ParquetDataCatalog(str(catalog_path))
    assert catalog.get_intervals(NautilusDataType.Bar, str(CANDLE_TYPE)) == [
        bounds(DAY)
    ]
    assert catalog.query(NautilusDataType.Bar, [str(CANDLE_TYPE)]) == []


@pytest.mark.unit
def test_a_day_without_a_raw_file_is_missing_and_not_written(
    raw: Path, catalog_path: Path
) -> None:
    RawFolder(raw).write_day(TradeTick, DAY, hourly(DAY))

    tally = run(raw, catalog_path, request(NEXT_DAY, "TradeTick"))

    assert outcomes(tally)[("TradeTick", NEXT_DAY)] is IngestOutcome.MISSING
    assert intervals(catalog_path, TRADES) == [bounds(DAY)]


@pytest.mark.unit
def test_known_gap_days_are_left_out(raw: Path, catalog_path: Path) -> None:
    source = LocalSource(frozenset({Gap(INSTRUMENT_ID, TradeTick, NEXT_DAY)}))
    RawFolder(raw).write_day(TradeTick, DAY, hourly(DAY))

    tally = run(raw, catalog_path, request(NEXT_DAY, "TradeTick"), source)

    assert list(outcomes(tally)) == [("TradeTick", DAY)]


@pytest.mark.unit
def test_a_rerun_skips_the_days_already_in_the_catalog(
    raw: Path, catalog_path: Path
) -> None:
    RawFolder(raw).write_day(TradeTick, DAY, hourly(DAY))
    run(raw, catalog_path, request(DAY, "TradeTick"))
    RawFolder(raw).write_day(TradeTick, DAY, hourly(DAY)[:1])
    RawFolder(raw).write_day(TradeTick, NEXT_DAY, hourly(NEXT_DAY))

    tally = run(raw, catalog_path, request(NEXT_DAY, "TradeTick"))

    assert outcomes(tally) == {
        ("TradeTick", DAY): IngestOutcome.SKIPPED,
        ("TradeTick", NEXT_DAY): IngestOutcome.WRITTEN,
    }
    trades = ParquetDataCatalog(str(catalog_path)).query(TRADES)
    assert len(trades) == 48


@pytest.mark.unit
def test_a_record_outside_its_day_fails_and_writes_nothing(
    raw: Path, catalog_path: Path
) -> None:
    RawFolder(raw).write_day(TradeTick, DAY, [start_of(DAY), start_of(NEXT_DAY)])

    with pytest.raises(OutsideDayError, match="1 records outside its UTC day"):
        run(raw, catalog_path, request(DAY, "TradeTick"))

    assert not (catalog_path / "data" / "trades").exists()


@pytest.mark.unit
@pytest.mark.parametrize("rows", [[], [8 * HOUR]])
def test_a_file_sbt2_writes_leaves_no_partial_file_behind(
    raw: Path, catalog_path: Path, rows: list[int]
) -> None:
    RawFolder(raw).write_day(
        FundingRateUpdate, DAY, [start_of(DAY) + each for each in rows]
    )

    run(raw, catalog_path, request(DAY, "FundingRateUpdate"))

    written = [each.name for each in catalog_path.rglob("*") if each.is_file()]
    assert not [each for each in written if "#" in each]


@pytest.mark.unit
def test_a_partial_file_left_by_a_crash_is_not_a_covered_day(
    raw: Path, catalog_path: Path
) -> None:
    leftover = catalog_path / "data" / "funding_rates" / str(INSTRUMENT_ID)
    leftover.mkdir(parents=True)
    (leftover / (_day_file_name(DAY) + "#sbt2")).write_bytes(b"trunc")
    RawFolder(raw).write_day(FundingRateUpdate, DAY, [start_of(DAY) + 8 * HOUR])

    tally = run(raw, catalog_path, request(DAY, "FundingRateUpdate"))

    assert outcomes(tally) == {("FundingRateUpdate", DAY): IngestOutcome.WRITTEN}
    fundings = ParquetDataCatalog(str(catalog_path)).query(
        NautilusDataType.FundingRateUpdate
    )
    assert [each.ts_event for each in fundings] == [start_of(DAY) + 8 * HOUR]


def _day_file_name(day: date) -> str:
    return f"{day}T00-00-00-000000000Z_{day}T23-59-59-999999999Z.parquet"


@pytest.mark.unit
def test_progress_hears_of_every_planned_day(raw: Path, catalog_path: Path) -> None:
    RawFolder(raw).write_day(TradeTick, DAY, hourly(DAY))
    recorder = Recorder()

    ingest(
        LocalSource(),
        request(NEXT_DAY, "TradeTick"),
        IngestOptions(raw, catalog_path, recorder),
    )

    assert recorder.days == 2
    assert [each.outcome for each in recorder.results] == [
        IngestOutcome.WRITTEN,
        IngestOutcome.MISSING,
    ]


@pytest.mark.unit
def test_progress_plans_only_the_days_it_ingests(raw: Path, catalog_path: Path) -> None:
    source = LocalSource(frozenset({Gap(INSTRUMENT_ID, TradeTick, NEXT_DAY)}))
    RawFolder(raw).write_day(TradeTick, DAY, hourly(DAY))
    recorder = Recorder()

    ingest(
        source,
        request(NEXT_DAY, "TradeTick"),
        IngestOptions(raw, catalog_path, recorder),
    )

    assert recorder.days == 1
    assert len(recorder.results) == 1


@pytest.mark.unit
def test_an_unserved_data_type_is_refused(raw: Path, catalog_path: Path) -> None:
    with pytest.raises(UnsupportedDataTypeError, match="OrderBookDelta"):
        run(raw, catalog_path, request(DAY, "OrderBookDelta"))


@pytest.mark.unit
def test_a_reversed_range_is_refused() -> None:
    with pytest.raises(ValueError, match="before"):
        DayRange((SYMBOL,), NEXT_DAY, DAY)
