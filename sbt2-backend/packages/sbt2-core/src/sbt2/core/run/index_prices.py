from collections.abc import Iterable
from datetime import timedelta

import pandas as pd
from nautilus_trader.model import CryptoOption, IndexPriceUpdate

from sbt2.core.market import index_id
from sbt2.core.spec import ResolvedRunSpec
from sbt2.data import Catalog, Window

_LOOKBACK = timedelta(days=1)


def read_index_prices(
    spec: ResolvedRunSpec, instruments: Iterable[object], catalog: Catalog
) -> dict[str, pd.Series]:
    """The index prices over the run of the underlying of each option among
    ``instruments``, by instrument id; none for a run with no option."""
    window = Window(spec.start - _LOOKBACK, spec.end)
    contracts = [each for each in instruments if isinstance(each, CryptoOption)]
    series: dict[str, pd.Series] = {}
    prices: dict[str, pd.Series] = {}
    for contract in contracts:
        index = index_id(contract)
        if str(index) not in series:
            frame = catalog.frame(index, IndexPriceUpdate, window)
            series[str(index)] = (
                pd.Series(frame["price"])
                if "price" in frame
                else pd.Series(dtype=float)
            )
        prices[str(contract.id)] = series[str(index)]
    return prices
