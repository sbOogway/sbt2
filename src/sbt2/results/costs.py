from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from functools import cached_property
from typing import Any

import numpy as np
import pandas as pd
from nautilus_trader.model import InstrumentId

from sbt2.data import Catalog, Gap
from sbt2.results.metrics import RunTables, Segment, equity_curve
from sbt2.results.money import total
from sbt2.results.pricing import Market, MissingPricesError, on_grid
from sbt2.results.trades import closed_trades
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


def costs_and_exposure(run: PricedRun) -> CostsAndExposure:
    """Costs, exposure, holding time and turnover over the part's dates.

    Positions are the stored fills' quantities, valued at the asset class's
    valuation price on the run's equity grid.
    """
    book = _Book(run)
    part = _Slice.of_run(book)
    return CostsAndExposure(
        total=_activity(_run_costs(part, book), part, book),
        by_instrument={
            instrument: _instrument_activity(part.of(instrument), book)
            for instrument in book.multipliers
        },
    )


class _Book:
    """The run's positions on its equity grid, one column per traded instrument."""

    def __init__(self, run: PricedRun) -> None:
        self.run = run
        self.segment = Segment.of_run(run.spec)
        self.equity = equity_curve(run.tables.equity, run.tables.currency, self.segment)

    @property
    def currency(self) -> str:
        return self.run.tables.currency

    @cached_property
    def quantities(self) -> pd.DataFrame:
        grid = self.segment.grid
        fills = self.run.tables.fills
        if fills.empty:
            return pd.DataFrame(index=grid)
        signed = pd.Series(
            _signed_quantities(fills), index=pd.DatetimeIndex(fills["ts_event"])
        )
        held = {
            str(instrument): on_grid(each.cumsum(), grid).fillna(0.0)
            for instrument, each in signed.groupby(fills["instrument_id"].to_numpy())
        }
        return pd.DataFrame(held, index=grid)

    @cached_property
    def multipliers(self) -> dict[str, float]:
        """Each traded instrument's contract multiplier; an inverse one fails."""
        ids = [InstrumentId.from_str(str(each)) for each in self.quantities.columns]
        instruments = _linear_instruments(ids, self.run.catalog)
        return {str(each): float(instruments[each].multiplier) for each in ids}

    @cached_property
    def notionals(self) -> pd.DataFrame:
        """Quantity times valuation price times contract multiplier."""
        market = Market(self.run.spec, self.run.catalog, self.run.known_gaps)
        price_type = self.run.spec.asset.valuation_price
        return pd.DataFrame(
            {
                instrument: self.quantities[instrument]
                * market.prices(InstrumentId.from_str(instrument), price_type)
                * multiplier
                for instrument, multiplier in self.multipliers.items()
            },
            index=self.segment.grid,
        )

    def traded_notional(self, fills: pd.DataFrame) -> pd.Series:
        """Each fill's quantity times its price times the contract multiplier."""
        multipliers = (
            fills["instrument_id"].astype(str).map(self.multipliers.__getitem__)
        )
        return (
            fills["last_qty"].astype(float)
            * fills["last_px"].astype(float)
            * multipliers
        )


def _linear_instruments(
    ids: list[InstrumentId], catalog: Catalog
) -> Mapping[InstrumentId, Any]:
    instruments = catalog.instruments(ids)
    missing = [str(each) for each in ids if each not in instruments]
    if missing:
        raise MissingPricesError(f"no instrument {', '.join(missing)} in the catalog")
    inverse = [str(each) for each in ids if instruments[each].is_inverse]
    if inverse:
        raise InverseInstrumentError(
            f"{', '.join(inverse)} is inverse; exposure values linear instruments only"
        )
    return instruments


@dataclass(frozen=True)
class _Slice:
    """The part's fills, carry and closed trades, and the positions they held,
    of the whole run or of one instrument."""

    fills: pd.DataFrame
    carry: pd.DataFrame
    trades: pd.DataFrame
    instruments: list[str]

    @classmethod
    def of_run(cls, book: _Book) -> _Slice:
        tables = book.run.tables
        return cls(
            _within(tables.fills, book.segment),
            _within(tables.carry, book.segment),
            closed_trades(tables.positions, tables.currency),
            list(book.multipliers),
        )

    def of(self, instrument: str) -> _Slice:
        return _Slice(
            _of(self.fills, instrument),
            _of(self.carry, instrument),
            _of(self.trades, instrument),
            [instrument],
        )

    def fees(self, currency: str) -> float:
        return -total(self.fills, "commission", currency)

    def carried(self, currency: str) -> float:
        return total(self.carry, "pnl_change", currency)


def _activity(costs: CostWaterfall, part: _Slice, book: _Book) -> Activity:
    return Activity(
        costs=costs,
        exposure=_exposure(part, book),
        holding_time=_holding_time(part.trades),
        turnover=_turnover(part, book),
    )


def _run_costs(part: _Slice, book: _Book) -> CostWaterfall:
    """Net PnL is the equity change; gross is what is left before fees and carry."""
    net = float(book.equity.iloc[-1] - book.equity.iloc[0])
    fees, carry = part.fees(book.currency), part.carried(book.currency)
    return CostWaterfall(net - fees - carry, fees, carry, net)


def _instrument_activity(part: _Slice, book: _Book) -> Activity:
    return _activity(_instrument_costs(part, book), part, book)


def _instrument_costs(part: _Slice, book: _Book) -> CostWaterfall:
    """Gross PnL is the fills' cash flow plus the change in the position's value,
    so net PnL is the realized plus the unrealized at the part end's price."""
    [notional] = [book.notionals[each] for each in part.instruments]
    paid = _sides(part.fills) * book.traded_notional(part.fills).to_numpy()
    gross = float(notional.iloc[-1] - notional.iloc[0] - paid.sum())
    fees, carry = part.fees(book.currency), part.carried(book.currency)
    return CostWaterfall(gross, fees, carry, gross + fees + carry)


def _signed_quantities(fills: pd.DataFrame) -> np.ndarray:
    return fills["last_qty"].astype(float).to_numpy() * _sides(fills)


def _sides(fills: pd.DataFrame) -> np.ndarray:
    """1 for a buy, -1 for a sell."""
    if fills.empty:
        return np.zeros(0)
    return np.where(fills["order_side"] == "BUY", 1.0, -1.0)


def _exposure(part: _Slice, book: _Book) -> Exposure:
    notionals = book.notionals.filter(items=part.instruments)
    return Exposure(
        gross_leverage=notionals.abs().sum(axis=1) / book.equity,
        net_leverage=notionals.sum(axis=1) / book.equity,
        time_in_market=_time_in_market(book.quantities.filter(items=part.instruments)),
    )


def _time_in_market(quantities: pd.DataFrame) -> float:
    """The share of grid steps that start with an open position."""
    open_at_start = (quantities.iloc[:-1] != 0).any(axis=1)
    return float(open_at_start.mean())


def _turnover(part: _Slice, book: _Book) -> float:
    """Traded notional over mean equity, per year of the asset's calendar."""
    if part.fills.empty:
        return 0.0
    traded = book.traded_notional(part.fills).sum()
    segment = book.segment
    years = (segment.end - segment.start) / timedelta(days=segment.days_per_year)
    return float(traded / book.equity.mean() / years)


def _holding_time(trades: pd.DataFrame) -> HoldingTime | None:
    """Over the closed positions and snapshots, as the trade statistics count them."""
    if trades.empty:
        return None
    nanos = pd.Series(trades["duration_ns"], dtype=float)
    return HoldingTime(mean=_duration(nanos.mean()), median=_duration(nanos.median()))


def _duration(nanos: float) -> timedelta:
    return timedelta(microseconds=nanos / 1_000)


def _within(frame: pd.DataFrame, segment: Segment) -> pd.DataFrame:
    if frame.empty:
        return frame
    at = pd.DatetimeIndex(frame["ts_event"])
    return frame.loc[(at >= segment.start) & (at <= segment.end)]


def _of(frame: pd.DataFrame, instrument: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.loc[frame["instrument_id"].astype(str) == instrument]
