from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any, override

import numpy as np
import pandas as pd
from nautilus_trader.analysis import ReportProvider
from nautilus_trader.common import Cache
from nautilus_trader.model import InstrumentId

from sbt2.core.assets.conventions.margin import MARGIN_COLUMNS, MarginModel
from sbt2.core.assets.option.margin.market import OptionMarket
from sbt2.core.assets.option.margin.rates import ContractHolding, MarginRates
from sbt2.core.market import Rates

type Timeline = tuple[np.ndarray, np.ndarray]


class OptionMarginModel(MarginModel):
    """Deribit's standard margin at the marks and index prices of the catalog."""

    def __init__(self, rates: MarginRates, market: OptionMarket) -> None:
        self._rates = rates
        self._market = market

    @override
    def initial(self, instrument: Any, quantity: Decimal, ts: int) -> Decimal:
        quote = self._market.quote(instrument, ts)
        return self._rates.initial_margin(ContractHolding(instrument, quantity), quote)

    @override
    def maintenance(self, instrument: Any, quantity: Decimal, ts: int) -> Decimal:
        quote = self._market.quote(instrument, ts)
        return self._rates.maintenance_margin(
            ContractHolding(instrument, quantity), quote
        )

    @override
    def value(self, instrument: Any, quantity: Decimal, ts: int) -> Decimal:
        mark = self._market.quote(instrument, ts).mark
        return quantity * Decimal(str(instrument.multiplier)) * mark

    @override
    def used(self, cache: Cache, grid: Sequence[int], rates: Rates) -> pd.DataFrame:
        fills = ReportProvider.generate_fills_report(cache.orders())
        timelines = _timelines(fills)
        own = [
            (slot, *row)
            for slot, ts in enumerate(grid)
            for row in self._rows(cache, timelines, (ts, rates.reporting))
        ]
        return _reported(pd.DataFrame(own, columns=["slot", *MARGIN_COLUMNS]), rates)

    def _rows(
        self, cache: Cache, timelines: dict[InstrumentId, Timeline], at: tuple[int, str]
    ) -> list[tuple[int, str, float, float]]:
        """The margin at ``at`` (a time and the currency of a flat book) in the
        coin of each contract held; one row of zeros when none is held."""
        ts, flat = at
        held: dict[str, list[tuple[Any, Decimal]]] = {}
        for instrument_id, timeline in timelines.items():
            if quantity := _held_before(timeline, ts):
                instrument = cache.instrument(instrument_id)
                if instrument is None:
                    raise LookupError(f"{instrument_id} is not a loaded instrument")
                coin = instrument.settlement_currency.code
                held.setdefault(coin, []).append((instrument, quantity))
        if not held:
            return [(ts, flat, 0.0, 0.0)]
        return [self._row(ts, coin, each) for coin, each in held.items()]

    def _row(
        self, ts: int, coin: str, held: list[tuple[Any, Decimal]]
    ) -> tuple[int, str, float, float]:
        initial = sum((self.initial(each, q, ts) for each, q in held), Decimal(0))
        kept = sum((self.maintenance(each, q, ts) for each, q in held), Decimal(0))
        return ts, coin, float(initial), float(kept)


def _reported(own: pd.DataFrame, rates: Rates) -> pd.DataFrame:
    """The margin rows with each coin's margin converted into the reporting
    currency and added, one row a time."""
    times = pd.DatetimeIndex(pd.to_datetime(own["ts_event"], unit="ns", utc=True))
    factors = rates.factors(list(own["currency"]), times)
    scaled = own.assign(
        currency=rates.reporting,
        margin_used=own["margin_used"] * factors,
        maintenance_margin=own["maintenance_margin"] * factors,
    )
    added = scaled.groupby("slot", sort=True).agg(
        {
            "ts_event": "first",
            "currency": "first",
            "margin_used": "sum",
            "maintenance_margin": "sum",
        }
    )
    return pd.DataFrame(added, columns=MARGIN_COLUMNS).reset_index(drop=True)


def _timelines(fills: pd.DataFrame) -> dict[InstrumentId, Timeline]:
    """For each instrument, the times of its fills in nanoseconds and the signed
    quantity held after each."""
    if fills.empty:
        return {}
    ordered = fills.sort_values("ts_event", kind="stable")
    return {
        InstrumentId.from_str(str(name)): _timeline(rows)
        for name, rows in ordered.groupby("instrument_id", sort=False)
    }


def _timeline(fills: pd.DataFrame) -> Timeline:
    times = pd.DatetimeIndex(fills["ts_event"]).as_unit("ns").asi8
    held = np.cumsum(np.array(list(_signed(fills.to_dict("records"))), dtype=object))
    return times, held


def _signed(fills: Iterable[dict[str, Any]]) -> Iterable[Decimal]:
    for fill in fills:
        sign = 1 if fill["order_side"] == "BUY" else -1
        yield sign * Decimal(str(fill["last_qty"]))


def _held_before(timeline: Timeline, ts: int) -> Decimal:
    times, held = timeline
    slot = int(np.searchsorted(times, ts, side="left")) - 1
    return Decimal(0) if slot < 0 else held[slot]
