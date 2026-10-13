from collections.abc import Mapping
from datetime import timedelta

import numpy as np

from sbt2.core.strategy.chain_records import ChainRecords

BASE = "BTC"
_DAY_NS = 86_400 * 10**9
_MIN_RETURNS = 5


def betas(records: Mapping[str, ChainRecords], lookback: timedelta) -> dict[str, float]:
    """The beta of each underlying to BTC: the covariance of their daily index
    returns over the variance of BTC's, over the ``lookback`` before now. It is 1
    for BTC, and for an underlying with fewer than five daily returns in the
    span, or while BTC's index did not move."""
    base = records.get(BASE)
    return {
        code: 1.0 if base is None or code == BASE else _beta(each, base, lookback)
        for code, each in records.items()
    }


def _beta(own: ChainRecords, base: ChainRecords, lookback: timedelta) -> float:
    since = own.now_ns() - int(lookback / timedelta(microseconds=1)) * 1_000
    returns = _paired_returns(own.daily_closes(since), base.daily_closes(since))
    if returns.shape[1] < _MIN_RETURNS:
        return 1.0
    variance = np.var(returns[1], ddof=1)
    if not variance > 0:
        return 1.0
    return float(np.cov(returns[0], returns[1])[0, 1] / variance)


def _paired_returns(own: dict[int, float], base: dict[int, float]) -> np.ndarray:
    """The returns of both over the days both closed on the day before: a row of
    the underlying's and a row of the base's."""
    pairs = [
        (own[day] / own[day - _DAY_NS] - 1, base[day] / base[day - _DAY_NS] - 1)
        for day in sorted(own.keys() & base.keys())
        if day - _DAY_NS in own and day - _DAY_NS in base
    ]
    return np.array(pairs, dtype=float).reshape(-1, 2).T
