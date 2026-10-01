from collections.abc import Sequence
from typing import Any

import pandas as pd
from nautilus_trader.model import Bar, BarType, InstrumentId

from sbt2.core.data.catalog.stored.stored_type import CatalogRoot, DayFile, StoredType
from sbt2.core.data.sources import candle_type


class Candles(StoredType):
    """The 1-minute candles, each stamped 1 ns before its close.

    Nautilus files bars under their bar type rather than their instrument.
    """

    data_type = Bar
    directory = "bars"
    metadata_fields = ("price_precision", "size_precision")

    def identifier(self, instrument_id: InstrumentId) -> str:
        return str(candle_type(instrument_id))

    def instrument_id(self, identifier: str) -> InstrumentId:
        return BarType.from_str(identifier).instrument_id

    def metadata(self, day: DayFile) -> dict[str, str]:
        instrument = day.instrument
        return {
            "instrument_id": str(instrument.id),
            "bar_type": self.identifier(instrument.id),
            **self._precisions(instrument),
        }

    def frame(self, records: Sequence[Any]) -> pd.DataFrame:
        return self._indexed(
            records,
            {
                name: [float(getattr(each, name)) for each in records]
                for name in ("open", "high", "low", "close", "volume")
            },
        )

    def _write_records(
        self, root: CatalogRoot, day: DayFile, records: Sequence[Any]
    ) -> None:
        root.nautilus.write_bars(list(records), *day.bounds)
