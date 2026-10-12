from datetime import UTC, datetime, timedelta

import pandas as pd
from nautilus_trader.model import (
    CryptoOption,
    IndexPriceUpdate,
    InstrumentId,
    OptionGreeks,
)

from sbt2.core.spec import ResolvedRunSpec
from sbt2.core.strategy import ChainHistory
from sbt2.data import Catalog, Window

_INDEX_REACH = timedelta(days=1)

type Span = tuple[datetime, datetime]
type Point = tuple[int, float]


def read_history(spec: ResolvedRunSpec, catalog: Catalog) -> ChainHistory | None:
    """What a chain run knew before its start, read from ``catalog``, as the
    nautilus run streams nothing from before it; none for a run with no chain."""
    index, volatility = spec.strategy.index, spec.strategy.volatility
    if index is None or volatility is None:
        return None
    start = spec.start
    indexes = _read(catalog, (index, IndexPriceUpdate), (start - _INDEX_REACH, start))
    levels = _read(catalog, (volatility, IndexPriceUpdate), _volatility_span(spec))
    return ChainHistory(
        _latest_ivs(spec, catalog),
        _last(_points(indexes, "price")),
        _points(levels, "price"),
    )


def _volatility_span(spec: ResolvedRunSpec) -> Span:
    return spec.volatility_window[0], spec.start


def _latest_ivs(spec: ResolvedRunSpec, catalog: Catalog) -> dict[InstrumentId, Point]:
    found: dict[InstrumentId, Point] = {}
    for contract in catalog.instruments(spec.strategy.instruments).values():
        if isinstance(contract, CryptoOption):
            records = _read(catalog, (contract.id, OptionGreeks), _life(contract, spec))
            latest = _last(_points(records, "mark_iv"))
            if latest is not None:
                found[contract.id] = latest
    return found


def _life(contract: CryptoOption, spec: ResolvedRunSpec) -> Span:
    return datetime.fromtimestamp(contract.activation_ns / 1e9, UTC), spec.start


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
