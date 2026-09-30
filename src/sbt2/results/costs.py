from dataclasses import dataclass

import pandas as pd

from sbt2.data import Catalog, Gap
from sbt2.results.metrics import RunTables, Segment, equity_curve
from sbt2.results.money import total
from sbt2.spec import ResolvedRunSpec


@dataclass(frozen=True)
class PricedRun:
    """A stored run with the catalog its positions are valued from.

    Prices are carried across ``known_gaps``, the days the run skipped.
    """

    spec: ResolvedRunSpec
    tables: RunTables
    catalog: Catalog
    known_gaps: frozenset[Gap] = frozenset()


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
class Activity:
    costs: CostWaterfall


@dataclass(frozen=True)
class CostsAndExposure:
    total: Activity


def costs_and_exposure(run: PricedRun) -> CostsAndExposure:
    """Costs, exposure, holding time and turnover over the part's dates."""
    segment = Segment.of_run(run.spec)
    curve = equity_curve(run.tables.equity, run.tables.currency, segment)
    net = float(curve.iloc[-1] - curve.iloc[0])
    return CostsAndExposure(total=Activity(costs=_waterfall(net, run, segment)))


def _waterfall(net: float, run: PricedRun, segment: Segment) -> CostWaterfall:
    currency = run.tables.currency
    fees = -total(_within(run.tables.fills, segment), "commission", currency)
    carry = total(_within(run.tables.carry, segment), "pnl_change", currency)
    return CostWaterfall(net - fees - carry, fees, carry, net)


def _within(frame: pd.DataFrame, segment: Segment) -> pd.DataFrame:
    if frame.empty:
        return frame
    at = pd.DatetimeIndex(frame["ts_event"])
    return frame.loc[(at >= segment.start) & (at <= segment.end)]
