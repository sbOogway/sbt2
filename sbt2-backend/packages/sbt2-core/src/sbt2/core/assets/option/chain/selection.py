from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from nautilus_trader.model import CryptoOption, IndexPriceUpdate, InstrumentId

from sbt2.core.assets.conventions.chain import ChainJob
from sbt2.core.assets.option.chain.chain import ChainBand, index_of, underlying_of
from sbt2.data import Window

_DAY_NS = 86_400 * 10**9
_BLOCK = 1_000


@dataclass(frozen=True)
class _Days:
    """The UTC days of the run's window, each from ``start`` to ``end`` in
    nanoseconds, with the lowest and highest index price in it. A day's prices
    include the one carried over from before."""

    start: np.ndarray
    end: np.ndarray
    low: np.ndarray
    high: np.ndarray


def select_contracts(job: ChainJob) -> list[InstrumentId]:
    """The contracts of the chain that, on some day of the window, are alive, have
    their days to expiry inside the band, and have a strike inside the band of
    that day's index prices."""
    band = ChainBand.from_table(job.table)
    contracts = _listed(job)
    if not contracts:
        return []
    days = _days(job)
    kept: list[InstrumentId] = []
    for block in _blocks(contracts):
        mask = _kept(block, days, band)
        kept.extend(each.id for each, keep in zip(block, mask, strict=True) if keep)
    return kept


def _blocks(contracts: list[CryptoOption]) -> list[list[CryptoOption]]:
    return [contracts[i : i + _BLOCK] for i in range(0, len(contracts), _BLOCK)]


def _listed(job: ChainJob) -> list[CryptoOption]:
    """The options of the chain's underlying in the catalog, by id."""
    prefix = f"{underlying_of(job.chain)}-"
    ids = [
        each
        for each in job.catalog.instrument_ids()
        if each.venue == job.chain.venue and each.symbol.value.startswith(prefix)
    ]
    found = job.catalog.instruments(ids)
    return [each for each in found.values() if isinstance(each, CryptoOption)]


def _days(job: ChainJob) -> _Days:
    start, end = job.window
    frame = job.catalog.frame(
        index_of(job.chain),
        IndexPriceUpdate,
        Window(start - timedelta(days=1), end),
    )
    times = pd.DatetimeIndex(frame.index).as_unit("ns").asi8
    prices = frame["price"].to_numpy(dtype=float)
    starts, ends = _day_bounds(start, end)
    ranges = [_range(times, prices, (a, b)) for a, b in zip(starts, ends, strict=True)]
    low = np.array([each[0] for each in ranges])
    high = np.array([each[1] for each in ranges])
    return _Days(starts, ends, low, high)


def _day_bounds(start: datetime, end: datetime) -> tuple[np.ndarray, np.ndarray]:
    first, last = pd.Timestamp(start).value, pd.Timestamp(end).value
    midnights = np.arange(first - first % _DAY_NS, last, _DAY_NS, dtype=np.int64)
    return np.maximum(midnights, first), np.minimum(midnights + _DAY_NS, last)


def _range(
    times: np.ndarray, prices: np.ndarray, day: tuple[int, int]
) -> tuple[float, float]:
    """The lowest and highest price from ``day``'s start to its end, with the last
    one before it; NaN when there is none."""
    first = int(np.searchsorted(times, day[0], side="left"))
    last = int(np.searchsorted(times, day[1], side="left"))
    seen = prices[max(first - 1, 0) : last]
    if seen.size == 0:
        return np.nan, np.nan
    return float(seen.min()), float(seen.max())


def _kept(block: list[CryptoOption], days: _Days, band: ChainBand) -> np.ndarray:
    """Whether each contract of the block is in the chain."""
    expiry = np.array([each.expiration_ns for each in block])[:, None]
    activation = np.array([each.activation_ns for each in block])[:, None]
    strike = np.array([float(each.strike_price) for each in block])[:, None]
    first = np.maximum(days.start, activation)
    last = np.minimum(days.end, expiry)
    near = (last > first) & (expiry - first >= band.min_dte * _DAY_NS)
    within = near & (expiry - last <= band.max_dte * _DAY_NS)
    spread = float(band.strike_band)
    inside = (strike >= days.low * (1 - spread)) & (strike <= days.high * (1 + spread))
    return (within & inside).any(axis=1)
