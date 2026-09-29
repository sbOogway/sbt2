from collections.abc import Sequence
from pathlib import Path
from typing import Any

from nautilus_trader.model import InstrumentId, NautilusDataType
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.data.catalog.stored import CatalogRoot, DayFile, stored_type


class CatalogWriter:
    """Writes whole files into a nautilus catalog; a file appears only once complete."""

    def __init__(self, path: Path) -> None:
        self._root = CatalogRoot(path, ParquetDataCatalog(str(path)))

    def has(self, day: DayFile) -> bool:
        stored = stored_type(day.data_type)
        intervals = self._catalog.get_intervals(
            stored.nautilus_type, stored.identifier(day.instrument.id)
        )
        return day.bounds in intervals

    def write(self, day: DayFile, records: Sequence[Any]) -> None:
        stored_type(day.data_type).write(self._root, day, records)

    def instrument(self, instrument_id: InstrumentId) -> Any | None:
        """The latest version of the instrument in the catalog, if any."""
        stored = self._catalog.instruments(instrument_ids=[str(instrument_id)])
        return max(stored, key=lambda each: each.ts_init, default=None)

    def write_instrument(self, instrument: Any) -> None:
        self._catalog.write_instruments([instrument])

    def remove(self, instrument_id: InstrumentId, data_types: Sequence[type]) -> None:
        """Every version of the instrument and all its ``data_types`` files."""
        for data_type in data_types:
            stored = stored_type(data_type)
            self._catalog.delete_data_range(
                stored.nautilus_type, stored.identifier(instrument_id)
            )
        for each in self._catalog.list_parquet_files(
            NautilusDataType.Instrument, str(instrument_id)
        ):
            (self._root.path / each).unlink()

    @property
    def _catalog(self) -> ParquetDataCatalog:
        return self._root.nautilus
