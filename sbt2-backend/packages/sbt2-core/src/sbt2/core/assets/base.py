from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol

from nautilus_trader.model import AssetClass, InstrumentClass, MarkPriceUpdate
from nautilus_trader.portfolio import PortfolioConfig


class Calendar(Protocol):
    def trading_days(self, start: datetime, end: datetime) -> list[date]:
        """UTC days with trading in the half-open window [start, end)."""
        ...


@dataclass(frozen=True)
class Carry:
    """A non-trade cost or income, settled natively by the venue."""

    data_types: tuple[type, ...]


class NoTakerRateError(LookupError):
    pass


@dataclass(frozen=True)
class BuyAndHoldConvention:
    """How a benchmark holds an instrument: bought once, then valued at ``price``.

    ``carry`` is what the holding accrues on top of the price.
    """

    price: type
    carry: Carry

    def entry_fee(self, venue: Mapping[str, Any]) -> Decimal:
        """The taker rate of the venue's fee model, paid once on entry.

        ``venue`` holds the run's venue arguments, the fee model as its
        ``{kind, config}`` table.
        """
        fee_model = venue.get("fee_model") or {}
        rate = fee_model.get("config", {}).get("taker_rate")
        if rate is None:
            name = fee_model.get("kind", "the venue's missing fee model")
            raise NoTakerRateError(f"{name} has no taker rate for a benchmark entry")
        return Decimal(str(rate))


@dataclass(frozen=True)
class AssetProfile:
    """What sbt2 needs to know about one nautilus asset class and instrument class."""

    asset_class: AssetClass
    instrument_class: InstrumentClass
    calendar: Calendar
    days_per_year: int
    carry: Carry
    venue_defaults: Mapping[str, Any]
    reference_prices: tuple[type, ...]
    valuation_price: type
    buy_and_hold: BuyAndHoldConvention

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
