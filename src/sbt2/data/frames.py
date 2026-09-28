from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd


def trades(records: Sequence[Any]) -> pd.DataFrame:
    return _frame(
        records,
        {
            "price": [float(each.price) for each in records],
            "size": [float(each.size) for each in records],
            "side": [each.aggressor_side.name for each in records],
            "trade_id": [str(each.trade_id) for each in records],
        },
    )


def mark_prices(records: Sequence[Any]) -> pd.DataFrame:
    return _frame(records, {"price": [float(each.value) for each in records]})


def funding(records: Sequence[Any]) -> pd.DataFrame:
    return _frame(
        records,
        {
            "rate": [float(each.rate) for each in records],
            "interval": [int(each.interval) for each in records],
        },
    )


def _frame(records: Sequence[Any], columns: Mapping[str, list[Any]]) -> pd.DataFrame:
    events = pd.to_datetime([each.ts_event for each in records], unit="ns", utc=True)
    return pd.DataFrame(columns, index=pd.DatetimeIndex(events, name="ts_event"))
