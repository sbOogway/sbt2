from datetime import timedelta

import pandas as pd

from sbt2.core.results.costs.book import Book, Slice, sides, signed_quantities
from sbt2.core.results.costs.records import (
    Activity,
    CostsAndExposure,
    CostWaterfall,
    Exposure,
    HoldingTime,
)
from sbt2.core.results.metrics import Segment
from sbt2.core.results.pricing import PricedRun


def costs_and_exposure(run: PricedRun) -> CostsAndExposure:
    """Costs, exposure, holding time and turnover over the part's dates.

    Positions are the stored fills' quantities, valued at the asset class's
    valuation price on the run's equity grid.
    """
    book = Book(run)
    part = Slice.of_run(book)
    return CostsAndExposure(
        total=_activity(_run_costs(part, book), part, book),
        by_instrument={
            instrument: _instrument_activity(part.of(instrument), book)
            for instrument in book.multipliers
        },
    )


def _activity(costs: CostWaterfall, part: Slice, book: Book) -> Activity:
    return Activity(
        costs=costs,
        exposure=_exposure(part, book),
        holding_time=_holding_time(part.trades),
        turnover=_turnover(part, book),
    )


def _run_costs(part: Slice, book: Book) -> CostWaterfall:
    """Net PnL is the equity change; gross is what is left before fees and carry."""
    net = float(book.equity.iloc[-1] - book.equity.iloc[0])
    fees, carry = part.fees(book.currency), part.carried(book.currency)
    return CostWaterfall(net - fees - carry, fees, carry, net)


def _instrument_activity(part: Slice, book: Book) -> Activity:
    return _activity(_instrument_costs(part, book), part, book)


def _instrument_costs(part: Slice, book: Book) -> CostWaterfall:
    """Gross PnL is the fills' cash flow plus the change in the position's value,
    so net PnL is the realized plus the unrealized at the part end's price."""
    [instrument] = part.instruments
    value = book.unit_values[instrument]
    held = book.quantities[instrument]
    opened = held.iloc[0] - _signed_at_start(part.fills, book.segment)
    paid = sides(part.fills) * book.traded_notional(part.fills).to_numpy()
    gross = float(held.iloc[-1] * value.iloc[-1] - opened * value.iloc[0] - paid.sum())
    fees, carry = part.fees(book.currency), part.carried(book.currency)
    return CostWaterfall(gross, fees, carry, gross + fees + carry)


def _signed_at_start(fills: pd.DataFrame, segment: Segment) -> float:
    """What the part's fills at its start traded, already in the start position
    but paid for within the part, like the fees counted from the start."""
    at_start = pd.DatetimeIndex(fills["ts_event"]) == segment.start
    return float(signed_quantities(fills)[at_start].sum())


def _exposure(part: Slice, book: Book) -> Exposure:
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


def _turnover(part: Slice, book: Book) -> float:
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
