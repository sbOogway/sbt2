from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    IndexPriceUpdate,
    InstrumentId,
    MarkPriceUpdate,
    NautilusDataType,
    OptionGreeks,
    Price,
    QuoteTick,
)
from nautilus_trader.persistence import ParquetDataCatalog
from option_catalog import INDEX_ID, OPTION_ID, option

from sbt2.core.assets import OptionHistory, QuoteJob, QuoteSettings, quote_ticks
from sbt2.core.assets.option_quote_catalog import write_quotes
from sbt2.data import Catalog, Window

DAY = datetime(2024, 1, 1, tzinfo=UTC)
RUN = (datetime(2024, 1, 8, tzinfo=UTC), datetime(2024, 1, 9, tzinfo=UTC))
QUOTED_DAYS = (0, 1, 2)
RUN_HOURS = range(7 * 24 + 3, 8 * 24)
SETTINGS = QuoteSettings(interval_seconds=3600)
INDEX_PRICE = 45_000.0


def nanos(hour: int) -> int:
    return dt_to_unix_nanos(DAY + timedelta(hours=hour))


def build_catalog(path: Path, hours: list[int]) -> None:
    """One call with marks and IV records at ``hours``, counted from 1 January,
    and the index every hour of the ten days."""
    path.mkdir()
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([option()])
    last = nanos(240)
    marks = [
        MarkPriceUpdate(
            OPTION_ID, Price(0.05 + 0.0001 * (hour % 7), 4), nanos(hour), nanos(hour)
        )
        for hour in hours
    ]
    greeks = [
        OptionGreeks(
            OPTION_ID,
            0.3,
            0.0001,
            10.0,
            -50.0,
            mark_iv=0.6 + 0.01 * (hour % 5),
            underlying_price=INDEX_PRICE,
            ts_event=nanos(hour),
            ts_init=nanos(hour),
        )
        for hour in hours
    ]
    index = [
        IndexPriceUpdate(INDEX_ID, Price(INDEX_PRICE, 2), nanos(hour), nanos(hour))
        for hour in range(240)
    ]
    catalog.write_mark_price_updates(marks, nanos(hours[0]), nanos(hours[-1]))
    catalog.write_option_greeks(greeks, nanos(hours[0]), nanos(hours[-1]))
    catalog.write_index_price_updates(index, nanos(0), last)


def days_before_the_run(days: tuple[int, ...]) -> list[int]:
    return [day * 24 + hour for day in days for hour in range(24)]


def run_hours() -> list[int]:
    return list(RUN_HOURS)


def quoted(folder: Path) -> list[QuoteTick]:
    return ParquetDataCatalog(str(folder)).query(
        NautilusDataType.QuoteTick, [str(OPTION_ID)]
    )


def quotes_folder(tmp_path: Path) -> Path:
    folder = tmp_path / "quotes"
    folder.mkdir(exist_ok=True)
    return folder


def job_of(catalog: Path) -> QuoteJob:
    return QuoteJob(catalog, [OPTION_ID], RUN, {})


@pytest.fixture
def mark_windows(monkeypatch: pytest.MonkeyPatch) -> list[Window]:
    windows: list[Window] = []
    frames: Callable[..., Any] = Catalog.frames

    def spy(
        self: Catalog,
        instrument_ids: Iterable[InstrumentId],
        data_type: type,
        window: Window,
    ) -> Any:
        if data_type is MarkPriceUpdate:
            windows.append(window)
        return frames(self, instrument_ids, data_type, window)

    monkeypatch.setattr(Catalog, "frames", spy)
    return windows


@pytest.mark.integration
def test_quotes_read_the_history_only_from_the_last_mark_before_the_run(
    tmp_path: Path, mark_windows: list[Window]
) -> None:
    hours = [*days_before_the_run((0, 1, 2, 6)), *run_hours()]
    build_catalog(tmp_path / "catalog", hours)

    write_quotes(job_of(tmp_path / "catalog"), SETTINGS, quotes_folder(tmp_path))

    assert min(each.start for each in mark_windows) == datetime(2024, 1, 7, tzinfo=UTC)


@pytest.mark.integration
def test_a_contract_whose_last_mark_is_days_before_the_run_quotes_from_it(
    tmp_path: Path,
) -> None:
    hours = [*days_before_the_run(QUOTED_DAYS), *run_hours()]
    build_catalog(tmp_path / "catalog", hours)

    write_quotes(job_of(tmp_path / "catalog"), SETTINGS, quotes_folder(tmp_path))

    [first, *_] = quoted(quotes_folder(tmp_path))
    assert first.ts_event == dt_to_unix_nanos(RUN[0])


@pytest.mark.integration
def test_the_quotes_are_the_same_as_with_the_full_history(tmp_path: Path) -> None:
    hours = [*days_before_the_run(QUOTED_DAYS), *run_hours()]
    build_catalog(tmp_path / "catalog", hours)
    catalog = Catalog(tmp_path / "catalog")
    window = Window(DAY, RUN[1])
    index = pd.Series(catalog.frame(INDEX_ID, IndexPriceUpdate, window)["price"])
    full = OptionHistory(
        option(),
        catalog.frame(OPTION_ID, MarkPriceUpdate, window),
        catalog.frame(OPTION_ID, OptionGreeks, window),
        index,
    )

    write_quotes(job_of(tmp_path / "catalog"), SETTINGS, quotes_folder(tmp_path))

    expected = quote_ticks(full, SETTINGS, RUN)
    assert expected
    assert quoted(quotes_folder(tmp_path)) == expected


def contract_ids(count: int) -> list[InstrumentId]:
    return [
        InstrumentId.from_str(f"BTC-1FEB24-{40000 + 1000 * k}-C.DERIBIT")
        for k in range(count)
    ]


def build_contracts_catalog(
    path: Path, contracts: dict[InstrumentId, list[int]]
) -> None:
    """``build_catalog`` with several calls, each with its own mark hours."""
    path.mkdir()
    catalog = ParquetDataCatalog(str(path))
    catalog.write_instruments([option(each) for each in contracts])
    for each, hours in contracts.items():
        catalog.write_mark_price_updates(
            [mark(each, hour) for hour in hours], nanos(hours[0]), nanos(hours[-1])
        )
        catalog.write_option_greeks(
            [greek(each, hour) for hour in hours], nanos(hours[0]), nanos(hours[-1])
        )
    index = [
        IndexPriceUpdate(INDEX_ID, Price(INDEX_PRICE, 2), nanos(hour), nanos(hour))
        for hour in range(240)
    ]
    catalog.write_index_price_updates(index, nanos(0), nanos(240))


def mark(instrument_id: InstrumentId, hour: int) -> MarkPriceUpdate:
    return MarkPriceUpdate(
        instrument_id, Price(0.05 + 0.0001 * (hour % 7), 4), nanos(hour), nanos(hour)
    )


def greek(instrument_id: InstrumentId, hour: int) -> OptionGreeks:
    return OptionGreeks(
        instrument_id,
        0.3,
        0.0001,
        10.0,
        -50.0,
        mark_iv=0.6 + 0.01 * (hour % 5),
        underlying_price=INDEX_PRICE,
        ts_event=nanos(hour),
        ts_init=nanos(hour),
    )


def mixed_hours(count: int) -> dict[InstrumentId, list[int]]:
    """Contracts that alternate between a last mark on the day before the run and
    one days before it, so half of them read from their activation."""
    recent = [*days_before_the_run((0, 6)), *run_hours()]
    old = [*days_before_the_run(QUOTED_DAYS), *run_hours()]
    return {
        each: recent if index % 2 else old
        for index, each in enumerate(contract_ids(count))
    }


def mixed_job(path: Path, count: int) -> QuoteJob:
    build_contracts_catalog(path, mixed_hours(count))
    return QuoteJob(path, contract_ids(count), RUN, {})


@pytest.fixture
def queries(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    query = ParquetDataCatalog.query

    def counted(self: ParquetDataCatalog, *args: Any, **kwargs: Any) -> Any:
        calls.append(args)
        return query(self, *args, **kwargs)

    monkeypatch.setattr(ParquetDataCatalog, "query", counted)
    return calls


def query_count(tmp_path: Path, count: int, queries: list[Any]) -> int:
    job = mixed_job(tmp_path / f"catalog{count}", count)
    folder = tmp_path / f"quotes{count}"
    folder.mkdir()
    queries.clear()
    write_quotes(job, SETTINGS, folder)
    return len(queries)


@pytest.mark.integration
def test_write_quotes_queries_the_catalog_a_fixed_number_of_times(
    tmp_path: Path, queries: list[Any]
) -> None:
    assert query_count(tmp_path, 2, queries) == query_count(tmp_path, 6, queries)


@pytest.mark.integration
def test_the_quotes_are_the_same_with_batched_reads(tmp_path: Path) -> None:
    job = mixed_job(tmp_path / "catalog", 4)
    catalog = Catalog(job.catalog)
    window = Window(DAY, RUN[1])
    index = pd.Series(catalog.frame(INDEX_ID, IndexPriceUpdate, window)["price"])
    expected = {
        each: quote_ticks(
            OptionHistory(
                option(each),
                catalog.frame(each, MarkPriceUpdate, window),
                catalog.frame(each, OptionGreeks, window),
                index,
            ),
            SETTINGS,
            RUN,
        )
        for each in job.instruments
    }

    write_quotes(job, SETTINGS, quotes_folder(tmp_path))

    stored = ParquetDataCatalog(str(quotes_folder(tmp_path)))
    for each, quotes in expected.items():
        assert quotes
        assert stored.query(NautilusDataType.QuoteTick, [str(each)]) == quotes


@pytest.mark.integration
def test_the_index_is_read_in_one_query_for_the_run(
    tmp_path: Path, queries: list[Any]
) -> None:
    build_catalog(tmp_path / "catalog", [*days_before_the_run((4,)), *run_hours()])
    week = (datetime(2024, 1, 5, tzinfo=UTC), RUN[1])
    job = QuoteJob(tmp_path / "catalog", [OPTION_ID], week, {})

    write_quotes(job, SETTINGS, quotes_folder(tmp_path))

    index_reads = [
        each for each in queries if each[0] == NautilusDataType.IndexPriceUpdate
    ]
    assert len(index_reads) == 1
