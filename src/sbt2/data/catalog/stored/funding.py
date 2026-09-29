from collections.abc import Sequence
from typing import Any

import pandas as pd
import pyarrow as pa
from nautilus_trader.model import FundingRateUpdate

from sbt2.data.catalog.stored.stored_type import CatalogRoot, DayFile, StoredType


class Funding(StoredType):
    data_type = FundingRateUpdate
    directory = "funding_rates"
    metadata_fields = ()

    def frame(self, records: Sequence[Any]) -> pd.DataFrame:
        return self._indexed(
            records,
            {
                "rate": [float(each.rate) for each in records],
                "interval": [int(each.interval) for each in records],
            },
        )

    def _write_records(
        self, root: CatalogRoot, day: DayFile, records: Sequence[Any]
    ) -> None:
        # Nautilus has no Python writer for funding.
        root.write_table(self._relative_path(day), self._table(records))

    def _table(self, fundings: Sequence[FundingRateUpdate]) -> pa.Table:
        columns = {
            "instrument_id": [str(each.instrument_id) for each in fundings],
            "rate": [str(each.rate) for each in fundings],
            "interval": [each.interval for each in fundings],
            "next_funding_ns": [each.next_funding_ns for each in fundings],
            "ts_event": [each.ts_event for each in fundings],
            "ts_init": [each.ts_init for each in fundings],
            "identifier": [str(each.instrument_id) for each in fundings],
        }
        return pa.table(columns, schema=self._arrow_schema())
