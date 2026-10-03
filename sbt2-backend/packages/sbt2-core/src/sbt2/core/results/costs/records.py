from dataclasses import dataclass
from datetime import timedelta

import pandas as pd


class InverseInstrumentError(ValueError):
    pass


@dataclass(frozen=True)
class CostWaterfall:
    """From gross PnL to net PnL, in the settlement currency.

    Fees are negative; carry is negative when paid and positive when received.
    """

    gross: float
    fees: float
    carry: float
    net: float


@dataclass(frozen=True)
class Exposure:
    """Leverage on the run's equity grid, and the share of its steps in the market."""

    gross_leverage: pd.Series
    net_leverage: pd.Series
    time_in_market: float


@dataclass(frozen=True)
class HoldingTime:
    """How long the closed trades were held."""

    mean: timedelta
    median: timedelta


@dataclass(frozen=True)
class Activity:
    """Costs, exposure and holding time; no holding time without a closed trade."""

    costs: CostWaterfall
    exposure: Exposure
    holding_time: HoldingTime | None
    turnover: float


@dataclass(frozen=True)
class CostsAndExposure:
    """The run's costs and exposure, and each traded instrument's by its id.

    The instruments' net PnLs add up to the run's.
    """

    total: Activity
    by_instrument: dict[str, Activity]
