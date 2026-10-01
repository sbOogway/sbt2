from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model import InstrumentId, NautilusDataType
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.serialization import get_arrow_schema_bytes

type Bounds = tuple[int, int]

# Nautilus's own writers stage under "<file>#N"; its reader ignores such names.
_PARTIAL_SUFFIX = "#sbt2"


@dataclass(frozen=True)
class DayFile:
    data_type: type
    instrument: Any
    bounds: Bounds


@dataclass(frozen=True)
class CatalogRoot:
    """A catalog's folder, and nautilus's catalog on it."""

    path: Path
    nautilus: ParquetDataCatalog

    def write_table(self, relative: Path, table: pa.Table) -> None:
        """Writes under a partial name and renames, as nautilus's writers do."""
        target = self.path / relative
        partial = target.with_name(target.name + _PARTIAL_SUFFIX)
        target.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, partial)
        partial.replace(target)


class StoredType(ABC):
    """A data type sbt2 stores in a catalog, laid out on disk as nautilus does."""

    data_type: ClassVar[type]
    directory: ClassVar[str]
    # The schema metadata nautilus's writers add, which its reader needs even
    # when a file has no rows to take them from.
    metadata_fields: ClassVar[tuple[str, ...]]

    @property
    def nautilus_type(self) -> NautilusDataType:
        return nautilus_type(self.data_type)

    def identifier(self, instrument_id: InstrumentId) -> str:
        """The name nautilus files an instrument's data under."""
        return str(instrument_id)

    def instrument_id(self, identifier: str) -> InstrumentId:
        """The inverse of ``identifier``."""
        return InstrumentId.from_str(identifier)

    def metadata(self, day: DayFile) -> dict[str, str]:
        instrument = day.instrument
        return {"instrument_id": str(instrument.id), **self._precisions(instrument)}

    def write(self, root: CatalogRoot, day: DayFile, records: Sequence[Any]) -> None:
        # Nautilus's writers write no file for an empty list.
        if records:
            self._write_records(root, day, records)
        else:
            root.write_table(self._relative_path(day), self._zero_rows(day))

    @abstractmethod
    def frame(self, records: Sequence[Any]) -> pd.DataFrame:
        """The records as columns indexed by event time."""

    @abstractmethod
    def _write_records(
        self, root: CatalogRoot, day: DayFile, records: Sequence[Any]
    ) -> None: ...

    def _precisions(self, instrument: Any) -> dict[str, str]:
        return {name: str(getattr(instrument, name)) for name in self.metadata_fields}

    def _relative_path(self, day: DayFile) -> Path:
        return Path(
            "data",
            self.directory,
            self.identifier(day.instrument.id),
            _file_name(day.bounds),
        )

    def _zero_rows(self, day: DayFile) -> pa.Table:
        schema = self._arrow_schema()
        metadata = {**(schema.metadata or {}), **self.metadata(day)}
        return schema.with_metadata(metadata).empty_table()

    def _arrow_schema(self) -> pa.Schema:
        schema = get_arrow_schema_bytes(self.data_type)
        return pa.ipc.read_schema(pa.py_buffer(schema))

    @staticmethod
    def _indexed(
        records: Sequence[Any], columns: Mapping[str, list[Any]]
    ) -> pd.DataFrame:
        events = pd.to_datetime(
            [each.ts_event for each in records], unit="ns", utc=True
        )
        return pd.DataFrame(columns, index=pd.DatetimeIndex(events, name="ts_event"))


def nautilus_type(data_type: type) -> NautilusDataType:
    return getattr(NautilusDataType, data_type.__name__)


def _file_name(bounds: Bounds) -> str:
    return "_".join(_file_timestamp(ts) for ts in bounds) + ".parquet"


def _file_timestamp(ts: int) -> str:
    seconds, nanos = divmod(ts, 1_000_000_000)
    moment = datetime.fromtimestamp(seconds, UTC)
    return f"{moment:%Y-%m-%dT%H-%M-%S}-{nanos:09d}Z"
