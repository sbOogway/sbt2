from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from nautilus_trader.model import CryptoOption, InstrumentId


@dataclass(frozen=True)
class ChainFeeds:
    """The series a chain strategy hears besides the contracts of the
    ``underlying`` (such as ``"BTC"``): the ``index`` the contracts are priced on
    and the ``volatility`` index of the underlying."""

    underlying: str
    index: InstrumentId
    volatility: InstrumentId


def underlying_index(code: str, venue: str) -> InstrumentId:
    """The id of the USD index of the underlying ``code`` on ``venue``."""
    return InstrumentId.from_str(f"{code}_USD.{venue}")


def index_id(contract: CryptoOption) -> InstrumentId:
    """The id of the series of index prices the contract's underlying has."""
    return underlying_index(contract.underlying.code, contract.id.venue.value)


class NoRateError(LookupError):
    pass


@dataclass(frozen=True)
class Rates:
    """What converts an amount into the ``reporting`` currency of a run: the USD
    index ``prices`` of each currency by time, so a coin is worth its price over
    the reporting currency's."""

    reporting: str
    prices: Mapping[str, pd.Series]

    def factors(self, currencies: Sequence[str], times: pd.DatetimeIndex) -> np.ndarray:
        """By what to multiply an amount in each of ``currencies`` at the matching
        time of ``times`` to have it in the reporting currency. A price holds
        until the next; ``NoRateError`` when a currency has none, or none yet."""
        factors = np.ones(len(times))
        named = np.asarray(currencies)
        for currency in set(currencies) - {self.reporting}:
            chosen = named == currency
            factors[chosen] = self._ratio(currency, times[chosen])
        return factors

    def _ratio(self, currency: str, times: pd.DatetimeIndex) -> np.ndarray:
        return self._price(currency, times) / self._price(self.reporting, times)

    def _price(self, currency: str, times: pd.DatetimeIndex) -> np.ndarray:
        series = self.prices.get(currency)
        if series is None or series.empty:
            raise NoRateError(f"no index price to convert {currency}")
        ordered = series.groupby(level=0).last().sort_index()
        last = ordered.index.searchsorted(times, side="right") - 1
        values = ordered.to_numpy(dtype=float)
        found = np.where(last >= 0, values[np.maximum(last, 0)], np.nan)
        if np.isnan(found).any():
            raise NoRateError(f"no index price of {currency} yet at some times")
        return found
