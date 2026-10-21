from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta

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


# The run reads index prices from a day before its start, and that day may be
# missing from the catalog; its first snapshot then precedes the first price.
_EARLY = timedelta(days=1)


class NoRateError(LookupError):
    pass


def _no_rates(columns: list[str]) -> pd.DataFrame:
    kinds = ["datetime64[ns, UTC]", "object", "float64"]
    return pd.DataFrame(
        {name: pd.Series(dtype=kind) for name, kind in zip(columns, kinds, strict=True)}
    )


@dataclass(frozen=True)
class Rates:
    """What converts an amount into the ``reporting`` currency of a run: the
    ``prices`` of each currency by time in one common unit, such as USD, so a coin
    is worth its price over the reporting currency's."""

    reporting: str
    prices: Mapping[str, pd.Series]

    @classmethod
    def from_table(cls, reporting: str, table: pd.DataFrame) -> Rates:
        """The rates a ``table`` of ``ts_event``, ``currency`` and ``rate`` holds:
        one unit of the currency in the reporting one at each time."""
        prices = {
            str(code): pd.Series(rows["rate"].to_numpy(), index=rows["ts_event"])
            for code, rows in table.groupby("currency")
        }
        always = pd.Series([1.0], index=pd.DatetimeIndex([pd.Timestamp(0, tz="UTC")]))
        return cls(reporting, {**prices, reporting: always})

    def table(self, times: pd.DatetimeIndex) -> pd.DataFrame:
        """The rate of each currency but the reporting one at each of ``times``,
        as ``from_table`` reads it."""
        others = sorted(set(self.prices) - {self.reporting})
        found = [
            pd.DataFrame(
                {
                    "ts_event": times,
                    "currency": code,
                    "rate": self.factors([code] * len(times), times),
                }
            )
            for code in others
        ]
        columns = ["ts_event", "currency", "rate"]
        return pd.concat(found, ignore_index=True) if found else _no_rates(columns)

    def factors(self, currencies: Sequence[str], times: pd.DatetimeIndex) -> np.ndarray:
        """By what to multiply an amount in each of ``currencies`` at the matching
        time of ``times`` to have it in the reporting currency. A price holds
        until the next, and from a day before the first; ``NoRateError`` when a
        currency has none, or none yet."""
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
        first = pd.DatetimeIndex(ordered.index)[0]
        early = (last < 0) & (times >= first - _EARLY)
        found = np.where((last >= 0) | early, values[np.maximum(last, 0)], np.nan)
        if np.isnan(found).any():
            raise NoRateError(f"no index price of {currency} yet at some times")
        return found
