from collections.abc import Callable
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
    frame: Callable[..., pd.DataFrame] = Catalog.frame

    def spy(
        self: Catalog, instrument_id: InstrumentId, data_type: type, window: Window
    ) -> Any:
        if data_type is MarkPriceUpdate:
            windows.append(window)
        return frame(self, instrument_id, data_type, window)

    monkeypatch.setattr(Catalog, "frame", spy)
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
