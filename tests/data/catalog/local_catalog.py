"""A catalog built by ingesting ``LocalSource`` days, a record an hour."""

from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

from local_source import (
    CANDLE_TYPE,
    INSTRUMENT_ID,
    SYMBOL,
    LocalSource,
    start_of,
    write_day,
)
from local_source import write_snapshot as write_raw_snapshot
from nautilus_trader.model import Bar, FundingRateUpdate, MarkPriceUpdate, TradeTick

from sbt2.data import DayRange, IngestOptions, IngestRequest, Window, ingest
from sbt2.data.sources import Gap

HOUR = 3_600_000_000_000
DAY = date(2024, 1, 1)
DIRECTORIES = {
    TradeTick: "trades",
    MarkPriceUpdate: "mark_prices",
    FundingRateUpdate: "funding_rates",
    Bar: "bars",
}


class LocalCatalog:
    def __init__(self, root: Path) -> None:
        self.raw = root / "raw"
        self.path = root / "catalog"
        write_raw_snapshot(self.raw, DAY)

    def add(self, data_type: type, *days: date, rows: int = 3) -> None:
        for each in days:
            self.write(data_type, each, _hourly(each, rows))

    def write(self, data_type: type, day: date, timestamps: list[int]) -> None:
        write_day(self.raw, data_type, day, timestamps)
        self._ingest(
            IngestRequest(DayRange((SYMBOL,), day, day, (data_type.__name__,)))
        )

    def rewrite(self, data_type: type, day: date, rows: int) -> None:
        for each in self._day_files(data_type, day):
            each.unlink()
        self.add(data_type, day, rows=rows)

    def reingest(self, margin_init: str, data_type: type, *days: date) -> None:
        write_raw_snapshot(self.raw, max(days) + timedelta(days=1), margin_init)
        for each in days:
            request = IngestRequest(
                DayRange((SYMBOL,), each, each, (data_type.__name__,)), reingest=True
            )
            self._ingest(request)

    def _ingest(self, request: IngestRequest) -> None:
        ingest(LocalSource(), request, IngestOptions(self.raw, self.path))

    def _day_files(self, data_type: type, day: date) -> list[Path]:
        identifier = CANDLE_TYPE if data_type is Bar else INSTRUMENT_ID
        folder = self.path / "data" / DIRECTORIES[data_type] / str(identifier)
        return list(folder.glob(f"{day.isoformat()}T*.parquet"))


def days(first: date, last: date) -> Window:
    """The window of whole UTC days from ``first`` to ``last``, included."""
    return Window(midnight(first), midnight(last + timedelta(days=1)))


def midnight(day: date) -> datetime:
    return datetime.combine(day, time(), UTC)


def gap(data_type: type, day: date) -> Gap:
    return Gap(INSTRUMENT_ID, data_type, day)


def _hourly(day: date, rows: int) -> list[int]:
    return [start_of(day) + k * HOUR for k in range(rows)]
