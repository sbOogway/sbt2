from collections.abc import Iterable
from datetime import timedelta

import pandas as pd
from nautilus_trader.model import CryptoOption, IndexPriceUpdate, InstrumentId

from sbt2.core.market import Rates, index_id, underlying_index
from sbt2.core.spec import ResolvedRunSpec
from sbt2.data import Catalog, Window

_LOOKBACK = timedelta(days=1)


def read_index_prices(
    spec: ResolvedRunSpec, instruments: Iterable[object], catalog: Catalog
) -> dict[str, pd.Series]:
    """The index prices over the run of the underlying of each option among
    ``instruments``, by instrument id; none for a run with no option."""
    window = _window(spec)
    contracts = [each for each in instruments if isinstance(each, CryptoOption)]
    series: dict[str, pd.Series] = {}
    prices: dict[str, pd.Series] = {}
    for contract in contracts:
        index = index_id(contract)
        if str(index) not in series:
            series[str(index)] = _series(catalog, index, window)
        prices[str(contract.id)] = series[str(index)]
    return prices


def read_rates(spec: ResolvedRunSpec, catalog: Catalog) -> Rates | None:
    """What converts the currencies of the run into its reporting currency, from
    the USD index of each; none for a run in one currency."""
    if len(spec.currencies) == 1:
        return None
    window = _window(spec)
    prices = {
        code: _series(catalog, underlying_index(code, spec.venue_name), window)
        for code in spec.currencies
    }
    return Rates(spec.currency, prices)


def _window(spec: ResolvedRunSpec) -> Window:
    return Window(spec.start - _LOOKBACK, spec.end)


def _series(catalog: Catalog, index: InstrumentId, window: Window) -> pd.Series:
    frame = catalog.frame(index, IndexPriceUpdate, window)
    return pd.Series(frame["price"]) if "price" in frame else pd.Series(dtype=float)
