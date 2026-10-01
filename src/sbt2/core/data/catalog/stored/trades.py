from collections.abc import Sequence
from typing import Any

import pandas as pd
from nautilus_trader.model import TradeTick

from sbt2.core.data.catalog.stored.stored_type import CatalogRoot, DayFile, StoredType


class Trades(StoredType):
    data_type = TradeTick
    directory = "trades"
    metadata_fields = ("price_precision", "size_precision")

    def frame(self, records: Sequence[Any]) -> pd.DataFrame:
        return self._indexed(
            records,
            {
                "price": [float(each.price) for each in records],
                "size": [float(each.size) for each in records],
                "side": [each.aggressor_side.name for each in records],
                "trade_id": [str(each.trade_id) for each in records],
            },
        )

    def _write_records(
        self, root: CatalogRoot, day: DayFile, records: Sequence[Any]
    ) -> None:
        root.nautilus.write_trade_ticks(list(records), *day.bounds)
