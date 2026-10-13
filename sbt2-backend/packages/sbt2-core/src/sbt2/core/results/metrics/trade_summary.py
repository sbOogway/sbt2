import math
import statistics

import pandas as pd

_TAIL = 0.05


def trade_statistics(
    trades: pd.DataFrame, margin: pd.DataFrame, currency: str
) -> dict[str, float | None]:
    """The statistics of the rows of a ``trade_table`` and of the buying power
    reduction in ``currency``, the ``margin_used`` of the margin table.

    The standard deviation is the sample's. The CVaR is the mean of the worst
    5 % of the trade P/Ls, rounded up to a whole trade, so the worst trade for
    20 or fewer. The P/L per day is the total P/L over the total days held.
    A run without trades has only its count.
    """
    return {**_trade_part(trades), **_bpr(margin, currency)}


def _trade_part(trades: pd.DataFrame) -> dict[str, float | None]:
    pls = [float(each) for each in trades["pl"]]
    if not pls:
        return {"Occurrences": 0}
    percents = [float(each) for each in trades["pl_percent"] if pd.notna(each)]
    days = sum(float(each) for each in trades["days_held"])
    return {
        "Occurrences": len(pls),
        "POP": sum(each > 0 for each in pls) / len(pls),
        "Average P/L": statistics.fmean(pls),
        "Average P/L %": statistics.fmean(percents) if percents else None,
        "P/L per Day": sum(pls) / days if days > 0 else None,
        "P/L Standard Deviation": statistics.stdev(pls) if len(pls) > 1 else None,
        "CVaR 5%": _cvar(pls),
        "Largest Loss": min(0.0, min(pls)),
    }


def _cvar(pls: list[float]) -> float:
    worst = sorted(pls)[: max(1, math.ceil(_TAIL * len(pls)))]
    return statistics.fmean(worst)


def _bpr(margin: pd.DataFrame, currency: str) -> dict[str, float | None]:
    if margin.empty:
        return {}
    used = [
        float(value)
        for value, each in zip(margin["margin_used"], margin["currency"], strict=True)
        if each == currency
    ]
    if not used:
        return {}
    return {"BPR Average": statistics.fmean(used), "BPR Peak": max(used)}
