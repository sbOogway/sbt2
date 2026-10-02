from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import numpy as np
import pandas as pd
from nautilus_trader.model import InstrumentId

from sbt2.core.data import Catalog
from sbt2.core.results.costs.records import InverseInstrumentError
from sbt2.core.results.metrics import Segment, closed_trades, total
from sbt2.core.results.pricing import MissingPricesError, PricedRun, on_grid


class Book:
    """The run's positions on its equity grid, one column per traded instrument."""

    def __init__(self, run: PricedRun) -> None:
        self.run = run
        self.segment = Segment.of_run(run.spec)
        self.equity = run.equity

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
            signed_quantities(fills), index=pd.DatetimeIndex(fills["ts_event"])
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
    def unit_values(self) -> pd.DataFrame:
        """Valuation price times contract multiplier: the value of one unit held."""
        market = self.run.market
        price_type = self.run.spec.asset.valuation_price
        return pd.DataFrame(
            {
                instrument: market.prices(InstrumentId.from_str(instrument), price_type)
                * multiplier
                for instrument, multiplier in self.multipliers.items()
            },
            index=self.segment.grid,
        )

    @cached_property
    def notionals(self) -> pd.DataFrame:
        return self.quantities.filter(items=self.multipliers) * self.unit_values

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
class Slice:
    """The part's fills, carry and closed trades, and the positions they held,
    of the whole run or of one instrument."""

    fills: pd.DataFrame
    carry: pd.DataFrame
    trades: pd.DataFrame
    instruments: list[str]

    @classmethod
    def of_run(cls, book: Book) -> Slice:
        tables = book.run.tables
        return cls(
            _within(tables.fills, book.segment),
            _within(tables.carry, book.segment),
            closed_trades(tables.positions, tables.currency),
            list(book.multipliers),
        )

    def of(self, instrument: str) -> Slice:
        return Slice(
            _of(self.fills, instrument),
            _of(self.carry, instrument),
            _of(self.trades, instrument),
            [instrument],
        )

    def fees(self, currency: str) -> float:
        return -total(self.fills, "commission", currency)

    def carried(self, currency: str) -> float:
        return total(self.carry, "pnl_change", currency)


def signed_quantities(fills: pd.DataFrame) -> np.ndarray:
    return fills["last_qty"].astype(float).to_numpy() * sides(fills)


def sides(fills: pd.DataFrame) -> np.ndarray:
    """1 for a buy, -1 for a sell."""
    if fills.empty:
        return np.zeros(0)
    return np.where(fills["order_side"] == "BUY", 1.0, -1.0)


def _within(frame: pd.DataFrame, segment: Segment) -> pd.DataFrame:
    if frame.empty:
        return frame
    at = pd.DatetimeIndex(frame["ts_event"])
    return frame.loc[(at >= segment.start) & (at <= segment.end)]


def _of(frame: pd.DataFrame, instrument: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    return frame.loc[frame["instrument_id"].astype(str) == instrument]
