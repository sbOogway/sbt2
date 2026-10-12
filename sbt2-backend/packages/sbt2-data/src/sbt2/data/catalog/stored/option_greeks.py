from collections.abc import Sequence
from typing import Any

import pandas as pd
from nautilus_trader.model import OptionGreeks

from sbt2.data.catalog.stored.stored_type import CatalogRoot, DayFile, StoredType


class OptionGreekRecords(StoredType):
    data_type = OptionGreeks
    directory = "option_greeks"
    metadata_fields = ()

    def frame(self, records: Sequence[Any]) -> pd.DataFrame:
        return self._indexed(
            records,
            {
                "delta": [each.delta for each in records],
                "gamma": [each.gamma for each in records],
                "vega": [each.vega for each in records],
                "theta": [each.theta for each in records],
                "mark_iv": [each.mark_iv for each in records],
                "underlying_price": [each.underlying_price for each in records],
            },
        )

    def _write_records(
        self, root: CatalogRoot, day: DayFile, records: Sequence[Any]
    ) -> None:
        root.nautilus.write_option_greeks(list(records), *day.bounds)
