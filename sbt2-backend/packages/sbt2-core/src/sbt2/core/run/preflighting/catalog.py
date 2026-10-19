from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, override

from nautilus_trader.model import InstrumentId

from sbt2.data import Catalog


class ReadOnceCatalog(Catalog):
    """A catalog that reads each instrument from disk once. Use it while the
    catalog does not change; make a new one after data is ingested."""

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self._read: dict[InstrumentId, Any | None] = {}

    @override
    def instruments(
        self, instrument_ids: Iterable[InstrumentId]
    ) -> Mapping[InstrumentId, Any]:
        ids = list(dict.fromkeys(instrument_ids))
        unread = [each for each in ids if each not in self._read]
        if unread:
            found = super().instruments(unread)
            self._read.update((each, found.get(each)) for each in unread)
        return {each: self._read[each] for each in ids if self._read[each] is not None}
