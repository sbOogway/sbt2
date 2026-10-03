import math
from collections.abc import Mapping

import pandas as pd
from nautilus_trader.analysis import PortfolioAnalyzer


def portfolio_analyzer(*statistics: object) -> PortfolioAnalyzer:
    analyzer = PortfolioAnalyzer()
    for statistic in statistics:
        analyzer.register_statistic(statistic)
    return analyzer


def nanos(returns: pd.Series) -> dict[int, float]:
    index = pd.DatetimeIndex(returns.index)
    return {
        int(ts.value): float(value) for ts, value in zip(index, returns, strict=True)
    }


def finite_values(statistics: Mapping[str, float]) -> dict[str, float | None]:
    return {name: finite(value) for name, value in statistics.items()}


def finite(value: float | None) -> float | None:
    return float(value) if value is not None and math.isfinite(value) else None
