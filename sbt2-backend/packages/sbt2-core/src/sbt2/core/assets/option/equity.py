from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

import pandas as pd
from nautilus_trader.analysis import ReportProvider
from nautilus_trader.common import Cache
from nautilus_trader.model import InstrumentId

from sbt2.core.assets.conventions.equity import CORRECTION_COLUMNS, EquityConvention


@dataclass
class _Holding:
    quantity: Decimal = Decimal(0)
    cost: Decimal = Decimal(0)

    def fill(self, signed_quantity: Decimal, price: Decimal) -> None:
        """Average-cost accounting of a netting position."""
        if self.quantity == 0 or (self.quantity > 0) == (signed_quantity > 0):
            self.cost += signed_quantity * price
        elif abs(signed_quantity) <= abs(self.quantity):
            self.cost *= (self.quantity + signed_quantity) / self.quantity
        else:
            self.cost = (self.quantity + signed_quantity) * price
        self.quantity += signed_quantity


class PremiumEquity(EquityConvention):
    """Nautilus takes the premium of an open option from the balance and counts
    it again in the unrealized P/L from the entry price. The correction is the
    cost of the open contracts, signed by side."""

    def corrections(self, cache: Cache) -> pd.DataFrame:
        fills = ReportProvider.generate_fills_report(cache.orders())
        if fills.empty:
            return pd.DataFrame(columns=CORRECTION_COLUMNS)
        fills = fills.sort_values("ts_event", kind="stable")
        return pd.DataFrame(_costs(fills, cache), columns=CORRECTION_COLUMNS)


def _costs(fills: pd.DataFrame, cache: Cache) -> Iterable[tuple[int, str, float]]:
    holdings: dict[InstrumentId, _Holding] = {}
    for fill in fills.to_dict("records"):
        instrument_id = InstrumentId.from_str(str(fill["instrument_id"]))
        sign = 1 if fill["order_side"] == "BUY" else -1
        holding = holdings.setdefault(instrument_id, _Holding())
        holding.fill(
            sign * Decimal(str(fill["last_qty"])), Decimal(str(fill["last_px"]))
        )
        currency = str(fill["currency"])
        yield (
            int(pd.Timestamp(fill["ts_event"]).value),
            currency,
            float(_open_cost(holdings, currency, cache)),
        )


def _open_cost(
    holdings: dict[InstrumentId, _Holding], currency: str, cache: Cache
) -> Decimal:
    total = Decimal(0)
    for instrument_id, holding in holdings.items():
        instrument = cache.instrument(instrument_id)
        if instrument is not None and instrument.settlement_currency.code == currency:
            total += holding.cost * Decimal(str(instrument.multiplier))
    return total
