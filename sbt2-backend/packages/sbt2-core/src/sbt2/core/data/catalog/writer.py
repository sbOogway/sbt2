from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nautilus_trader.model import InstrumentId, NautilusDataType
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.core.data.catalog.stored import Bounds, CatalogRoot, DayFile, stored_type

type _Series = tuple[NautilusDataType, str]


class CatalogWriter:
    """Writes whole files into a nautilus catalog; a file appears only once complete.

    Each series' intervals are read from the catalog once and then kept by the
    writer, so it must be the only one writing those series while it lives.
    """

    def __init__(self, path: Path) -> None:
        self._root = CatalogRoot(path, ParquetDataCatalog(str(path)))
        self._intervals: dict[_Series, set[Bounds]] = {}

    def has(self, day: DayFile) -> bool:
        return day.bounds in self._series_intervals(_series_of(day))

    def write(self, day: DayFile, records: Sequence[Any]) -> None:
        stored_type(day.data_type).write(self._root, day, records)
        self._series_intervals(_series_of(day)).add(day.bounds)

    def instrument(self, instrument_id: InstrumentId) -> Any | None:
        """The latest version of the instrument in the catalog, if any."""
        stored = self._catalog.instruments(instrument_ids=[str(instrument_id)])
        return max(stored, key=lambda each: each.ts_init, default=None)

    def write_instrument(self, instrument: Any) -> None:
        self._catalog.write_instruments([instrument])

    def remove(self, instrument_id: InstrumentId, data_types: Sequence[type]) -> None:
        """Every version of the instrument and all its ``data_types`` files."""
        for data_type in data_types:
            series = _series(data_type, instrument_id)
            self._catalog.delete_data_range(*series)
            self._intervals.pop(series, None)
        for each in self._catalog.list_parquet_files(
            NautilusDataType.Instrument, str(instrument_id)
        ):
            (self._root.path / each).unlink()

    def _series_intervals(self, series: _Series) -> set[Bounds]:
        if series not in self._intervals:
            self._intervals[series] = set(self._catalog.get_intervals(*series))
        return self._intervals[series]

    @property
    def _catalog(self) -> ParquetDataCatalog:
        return self._root.nautilus


def _series_of(day: DayFile) -> _Series:
    return _series(day.data_type, day.instrument.id)


def _series(data_type: type, instrument_id: InstrumentId) -> _Series:
    stored = stored_type(data_type)
    return stored.nautilus_type, stored.identifier(instrument_id)
