from collections.abc import Sequence
from typing import Any

import pandas as pd
from nautilus_trader.model import IndexPriceUpdate

from sbt2.data.catalog.stored.stored_type import CatalogRoot, DayFile, StoredType


class IndexPrices(StoredType):
    data_type = IndexPriceUpdate
    directory = "index_prices"
    metadata_fields = ("price_precision",)

    def frame(self, records: Sequence[Any]) -> pd.DataFrame:
        return self._indexed(
            records, {"price": [float(each.value) for each in records]}
        )

    def _write_records(
        self, root: CatalogRoot, day: DayFile, records: Sequence[Any]
    ) -> None:
        root.nautilus.write_index_price_updates(list(records), *day.bounds)
