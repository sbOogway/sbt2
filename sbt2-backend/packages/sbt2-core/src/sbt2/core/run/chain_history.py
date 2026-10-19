from datetime import UTC, datetime, timedelta

import pandas as pd
from nautilus_trader.model import (
    CryptoOption,
    IndexPriceUpdate,
    InstrumentId,
    OptionGreeks,
)

from sbt2.core.market import ChainFeeds
from sbt2.core.spec import ResolvedRunSpec
from sbt2.core.strategy import ChainHistory
from sbt2.data import Catalog, Window

_INDEX_REACH = timedelta(days=1)
_IV_REACH = timedelta(days=1)
_SEVERAL = 2

type Span = tuple[datetime, datetime]
type Point = tuple[int, float]


def read_histories(spec: ResolvedRunSpec, catalog: Catalog) -> dict[str, ChainHistory]:
    """What each chain of a run knew before its start, by underlying, read from
    ``catalog``, as the nautilus run streams nothing from before it; none for a
    run with no chain."""
    return {
        each.underlying: _history(spec, each, catalog) for each in spec.strategy.feeds
    }


def _history(
    spec: ResolvedRunSpec, feeds: ChainFeeds, catalog: Catalog
) -> ChainHistory:
    start = spec.start
    index = (feeds.index, IndexPriceUpdate)
    indexes = _read(catalog, index, (start - _INDEX_REACH, start))
    levels = _read(
        catalog, (feeds.volatility, IndexPriceUpdate), _volatility_span(spec)
    )
    return ChainHistory(
        _latest_ivs(spec, feeds.underlying, catalog),
        _last(_points(indexes, "price")),
        _points(levels, "price"),
        _closes(spec, index, catalog),
    )


def _closes(
    spec: ResolvedRunSpec, index: tuple[InstrumentId, type], catalog: Catalog
) -> list[Point]:
    """The index price at each midnight of the look-back, which only the betas of
    several chains need."""
    if len(spec.strategy.feeds) < _SEVERAL:
        return []
    span = (spec.start - spec.lookback, spec.start)
    frame = _read(catalog, index, span)
    if frame.empty:
        return []
    prices = frame["price"].dropna().sort_index()
    midnights = pd.date_range(pd.Timestamp(span[0]).ceil("D"), span[1], freq="D")
    found = prices.index.searchsorted(midnights, side="right") - 1
    return [
        (int(midnight.value), float(prices.iloc[slot]))
        for midnight, slot in zip(midnights, found, strict=True)
        if slot >= 0
    ]


def _volatility_span(spec: ResolvedRunSpec) -> Span:
    return spec.volatility_window[0], spec.start


def _latest_ivs(
    spec: ResolvedRunSpec, underlying: str, catalog: Catalog
) -> dict[InstrumentId, Point]:
    """The last IV of each contract before the run. Most contracts have one in the
    day before it; only the others are read from their activation."""
    contracts = [
        each
        for each in catalog.instruments(spec.strategy.instruments).values()
        if isinstance(each, CryptoOption)
        and each.underlying.code == underlying
        and _activation(each) < spec.start
    ]
    recent = spec.start - _IV_REACH
    found = _ivs(catalog, contracts, (recent, spec.start))
    stale = [
        each
        for each in contracts
        if each.id not in found and _activation(each) < recent
    ]
    if stale:
        since = min(_activation(each) for each in stale)
        found |= _ivs(catalog, stale, (since, spec.start))
    return {each.id: found[each.id] for each in contracts if each.id in found}


def _ivs(
    catalog: Catalog, contracts: list[CryptoOption], span: Span
) -> dict[InstrumentId, Point]:
    """The last IV of each contract over ``span``, from its activation on."""
    ids = [each.id for each in contracts]
    frames = catalog.frames(ids, OptionGreeks, Window(*span))
    found: dict[InstrumentId, Point] = {}
    for each in contracts:
        frame = frames[each.id]
        latest = _last(_points(frame.loc[frame.index >= _activation(each)], "mark_iv"))
        if latest is not None:
            found[each.id] = latest
    return found


def _activation(contract: CryptoOption) -> datetime:
    return datetime.fromtimestamp(contract.activation_ns / 1e9, UTC)


def _read(
    catalog: Catalog, series: tuple[InstrumentId, type], span: Span
) -> pd.DataFrame:
    """The records of the series over ``span``; none for an empty span."""
    begin, end = span
    if end <= begin:
        return pd.DataFrame()
    return catalog.frame(series[0], series[1], Window(begin, end))


def _points(frame: pd.DataFrame, column: str) -> list[Point]:
    """The ``(ns, value)`` pairs of ``column``, without the missing values."""
    if frame.empty:
        return []
    values = frame[column].dropna()
    times = pd.DatetimeIndex(values.index).as_unit("ns").asi8
    return list(zip(map(int, times), map(float, values), strict=True))


def _last(points: list[Point]) -> Point | None:
    return points[-1] if points else None
