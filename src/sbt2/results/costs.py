from dataclasses import dataclass
from functools import cached_property

import numpy as np
import pandas as pd
from nautilus_trader.model import InstrumentId

from sbt2.data import Catalog, Gap
from sbt2.results.metrics import RunTables, Segment, equity_curve
from sbt2.results.money import total
from sbt2.results.pricing import Market, MissingPricesError, on_grid
from sbt2.spec import ResolvedRunSpec


class InverseInstrumentError(ValueError):
    pass


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
class Exposure:
    """Leverage on the run's equity grid, and the share of its steps in the market."""

    gross_leverage: pd.Series
    net_leverage: pd.Series
    time_in_market: float


@dataclass(frozen=True)
class Activity:
    costs: CostWaterfall
    exposure: Exposure


@dataclass(frozen=True)
class CostsAndExposure:
    total: Activity


def costs_and_exposure(run: PricedRun) -> CostsAndExposure:
    """Costs, exposure, holding time and turnover over the part's dates.

    Positions are the stored fills' quantities, valued at the asset class's
    valuation price on the run's equity grid.
    """
    book = _Book(run)
    net = float(book.equity.iloc[-1] - book.equity.iloc[0])
    return CostsAndExposure(
        total=Activity(
            costs=_waterfall(net, run, book.segment),
            exposure=_exposure(book.notionals, book),
        )
    )


class _Book:
    """The run's positions on its equity grid, one column per traded instrument."""

    def __init__(self, run: PricedRun) -> None:
        self._run = run
        self.segment = Segment.of_run(run.spec)
        self.equity = equity_curve(run.tables.equity, run.tables.currency, self.segment)

    @cached_property
    def quantities(self) -> pd.DataFrame:
        grid = self.segment.grid
        fills = self._run.tables.fills
        if fills.empty:
            return pd.DataFrame(index=grid)
        signed = _signed_quantities(fills)
        held = {
            str(instrument): on_grid(each.cumsum(), grid).fillna(0.0)
            for instrument, each in signed.groupby(fills["instrument_id"].to_numpy())
        }
        return pd.DataFrame(held, index=grid)

    @cached_property
    def notionals(self) -> pd.DataFrame:
        """Quantity times valuation price times contract multiplier."""
        market = Market(self._run.spec, self._run.catalog, self._run.known_gaps)
        price_type = self._run.spec.asset.valuation_price
        ids = [InstrumentId.from_str(str(each)) for each in self.quantities.columns]
        multipliers = _linear_multipliers(ids, self._run.catalog)
        return pd.DataFrame(
            {
                str(each): self.quantities[str(each)]
                * market.prices(each, price_type)
                * multipliers[each]
                for each in ids
            },
            index=self.segment.grid,
        )


def _linear_multipliers(
    ids: list[InstrumentId], catalog: Catalog
) -> dict[InstrumentId, float]:
    """Each instrument's contract multiplier; an inverse instrument fails."""
    instruments = catalog.instruments(ids)
    missing = [str(each) for each in ids if each not in instruments]
    if missing:
        raise MissingPricesError(f"no instrument {', '.join(missing)} in the catalog")
    inverse = [str(each) for each in ids if instruments[each].is_inverse]
    if inverse:
        raise InverseInstrumentError(
            f"{', '.join(inverse)} is inverse; exposure values linear instruments only"
        )
    return {each: float(instruments[each].multiplier) for each in ids}


def _signed_quantities(fills: pd.DataFrame) -> pd.Series:
    sign = np.where(fills["order_side"] == "BUY", 1.0, -1.0)
    signed = fills["last_qty"].astype(float).to_numpy() * sign
    return pd.Series(signed, index=pd.DatetimeIndex(fills["ts_event"]))


def _exposure(notionals: pd.DataFrame, book: _Book) -> Exposure:
    return Exposure(
        gross_leverage=notionals.abs().sum(axis=1) / book.equity,
        net_leverage=notionals.sum(axis=1) / book.equity,
        time_in_market=_time_in_market(book.quantities),
    )


def _time_in_market(quantities: pd.DataFrame) -> float:
    """The share of grid steps that start with an open position."""
    open_at_start = (quantities.iloc[:-1] != 0).any(axis=1)
    return float(open_at_start.mean())


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
