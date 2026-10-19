from collections.abc import Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import numpy as np
import pandas as pd
from nautilus_trader.model import CryptoOption, InstrumentId

from sbt2.core.results.metrics import RunTables, Segment, closed_trades
from sbt2.core.results.pricing import MissingPricesError, PricedRun, on_grid
from sbt2.data import Catalog


class Book:
    """The run's positions on its equity grid, one column per traded instrument."""

    def __init__(self, run: PricedRun) -> None:
        self.run = run
        self.segment = Segment.of_run(run.spec)
        self.equity = run.equity

    @property
    def tables(self) -> RunTables:
        return self.run.tables

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
    def _instruments(self) -> dict[str, Any]:
        """Each traded instrument."""
        ids = [InstrumentId.from_str(str(each)) for each in self.quantities.columns]
        found = _listed_instruments(ids, self.run.catalog)
        return {str(each): found[each] for each in ids}

    @cached_property
    def multipliers(self) -> dict[str, float]:
        """Each traded instrument's contract multiplier."""
        return {k: float(each.multiplier) for k, each in self._instruments.items()}

    @cached_property
    def directions(self) -> dict[str, float]:
        """1 for a linear instrument, whose position is worth its quantity times
        the price, and -1 for an inverse one, whose position is worth minus its
        quantity over the price: the gain of a long is what its entry gains over
        its exit, in the coin."""
        return {
            k: -1.0 if _is_inverse(each) else 1.0
            for k, each in self._instruments.items()
        }

    @cached_property
    def coins(self) -> dict[str, str]:
        """The currency each traded instrument is valued in."""
        return {
            k: each.settlement_currency.code for k, each in self._instruments.items()
        }

    @cached_property
    def unit_values(self) -> pd.DataFrame:
        """The size of one unit held, in the reporting currency: the valuation
        price times the contract multiplier, or for an inverse instrument the
        multiplier over the price."""
        market = self.run.market
        price_type = self.run.spec.asset.valuation_price
        grid = self.segment.grid
        return pd.DataFrame(
            {
                instrument: _size(
                    market.prices(InstrumentId.from_str(instrument), price_type),
                    multiplier,
                    self.directions[instrument],
                )
                * self._factors([self.coins[instrument]] * len(grid), grid)
                for instrument, multiplier in self.multipliers.items()
            },
            index=grid,
        )

    def _factors(self, coins: list[str], times: pd.DatetimeIndex) -> np.ndarray:
        """By what the values in ``coins`` convert into the reporting currency; a
        run in one currency has its values as they are."""
        if self.tables.rates is None:
            return np.ones(len(times))
        return self.tables.factors(coins, times)

    @cached_property
    def notionals(self) -> pd.DataFrame:
        return self.quantities.filter(items=self.multipliers) * self.unit_values

    def traded_notional(self, fills: pd.DataFrame) -> pd.Series:
        """Each fill's size: its quantity times its price times the contract
        multiplier, or for an inverse instrument the multiplier over the price."""
        names = fills["instrument_id"].astype(str)
        times = pd.DatetimeIndex(pd.to_datetime(fills["ts_event"], utc=True))
        factors = self._factors([self.coins[each] for each in names], times)
        return (
            fills["last_qty"].astype(float)
            * _size(
                fills["last_px"].astype(float),
                names.map(self.multipliers.__getitem__),
                names.map(self.directions.__getitem__),
            )
            * factors
        )

    def cash_paid(self, fills: pd.DataFrame) -> np.ndarray:
        """What the fills paid, signed: negative for a buy of an inverse
        instrument, whose position is a liability worth minus its size."""
        names = fills["instrument_id"].astype(str)
        directions = names.map(self.directions.__getitem__).to_numpy(dtype=float)
        return sides(fills) * self.traded_notional(fills).to_numpy() * directions


def _size(prices: Any, multiplier: Any, direction: Any) -> Any:
    """``price * multiplier`` for a direction of 1, ``multiplier / price`` for -1."""
    return np.where(direction > 0, prices * multiplier, multiplier / prices)


def _listed_instruments(
    ids: list[InstrumentId], catalog: Catalog
) -> Mapping[InstrumentId, Any]:
    instruments = catalog.instruments(ids)
    missing = [str(each) for each in ids if each not in instruments]
    if missing:
        raise MissingPricesError(f"no instrument {', '.join(missing)} in the catalog")
    return instruments


def _is_inverse(instrument: Any) -> bool:
    """An option is priced in its settlement coin, so it values like a linear one."""
    return bool(instrument.is_inverse) and not isinstance(instrument, CryptoOption)


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
            closed_trades(tables.positions, tables.currency, tables.rates),
            list(book.multipliers),
        )

    def of(self, instrument: str) -> Slice:
        return Slice(
            _of(self.fills, instrument),
            _of(self.carry, instrument),
            _of(self.trades, instrument),
            [instrument],
        )

    def fees(self, tables: RunTables) -> float:
        return -tables.total(self.fills, "commission")

    def carried(self, tables: RunTables) -> float:
        return tables.total(self.carry, "pnl_change")


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
