from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol

from nautilus_trader.backtest import SimulationModule
from nautilus_trader.model import AssetClass, InstrumentClass, MarkPriceUpdate
from nautilus_trader.portfolio import PortfolioConfig


class Calendar(Protocol):
    def trading_days(self, start: datetime, end: datetime) -> list[date]:
        """UTC days with trading in the half-open window [start, end)."""
        ...


@dataclass(frozen=True)
class Carry:
    """A non-trade cost or income, settled natively by the venue unless a module is given."""

    name: str
    data_types: tuple[type, ...]
    module: Callable[[], SimulationModule] | None = None


@dataclass(frozen=True)
class BuyAndHold:
    pays_carry: bool
    pays_entry_fee: bool
    pays_exit_fee: bool


@dataclass(frozen=True)
class AssetProfile:
    """What sbt2 needs to know about one nautilus asset class and instrument class."""

    asset_class: AssetClass
    instrument_class: InstrumentClass
    instrument_type: type
    calendar: Calendar
    days_per_year: int
    carry: Carry
    venue_defaults: Mapping[str, Any]
    reference_prices: tuple[type, ...]
    valuation_price: type
    buy_and_hold: BuyAndHold

    def covers(self, instrument: Any) -> bool:
        return (
            instrument.asset_class == self.asset_class
            and instrument.instrument_class == self.instrument_class
        )

    def portfolio_config(self, snapshot_interval_ms: int) -> PortfolioConfig:
        return PortfolioConfig(
            use_mark_prices=self.valuation_price is MarkPriceUpdate,
            snapshot_interval_ms=snapshot_interval_ms,
        )
