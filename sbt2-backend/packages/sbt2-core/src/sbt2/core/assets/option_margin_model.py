from collections.abc import Iterable, Sequence
from decimal import Decimal
from typing import Any, override

import numpy as np
import pandas as pd
from nautilus_trader.analysis import ReportProvider
from nautilus_trader.common import Cache
from nautilus_trader.model import InstrumentId

from sbt2.core.assets.base import MARGIN_COLUMNS, MarginModel
from sbt2.core.assets.option_margin import ContractHolding, MarginRates
from sbt2.core.assets.option_margin_market import OptionMarket

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
    def used(self, cache: Cache, grid: Sequence[int], currency: str) -> pd.DataFrame:
        fills = ReportProvider.generate_fills_report(cache.orders())
        timelines = _timelines(fills)
        rows = [self._row(cache, timelines, (ts, currency)) for ts in grid]
        return pd.DataFrame(rows, columns=MARGIN_COLUMNS)

    def _row(
        self, cache: Cache, timelines: dict[InstrumentId, Timeline], at: tuple[int, str]
    ) -> tuple[int, str, float, float]:
        ts, currency = at
        held = [
            (cache.instrument(instrument_id), quantity)
            for instrument_id, timeline in timelines.items()
            if (quantity := _held_before(timeline, ts))
        ]
        initial = sum((self.initial(each, q, ts) for each, q in held), Decimal(0))
        kept = sum((self.maintenance(each, q, ts) for each, q in held), Decimal(0))
        return ts, currency, float(initial), float(kept)


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
