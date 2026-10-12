from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import pandas as pd
from nautilus_trader.backtest import BacktestDataConfig
from nautilus_trader.common import Cache
from nautilus_trader.model import (
    AssetClass,
    BarSpecification,
    InstrumentClass,
    InstrumentId,
    MarkPriceUpdate,
)
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


class NoBuyAndHoldError(LookupError):
    pass


@dataclass(frozen=True)
class NoBuyAndHold(BuyAndHoldConvention):
    """The convention of an instrument that cannot be held as a benchmark."""

    price: type = MarkPriceUpdate
    carry: Carry = Carry(data_types=())
    reason: str = ""

    def entry_fee(self, venue: Mapping[str, Any]) -> Decimal:
        del venue
        raise NoBuyAndHoldError(f"no buy-and-hold benchmark: {self.reason}")


CORRECTION_COLUMNS = ["ts_event", "currency", "amount"]


class EquityConvention(ABC):
    """How the equity nautilus reports differs from the true equity."""

    @abstractmethod
    def corrections(self, cache: Cache) -> pd.DataFrame:
        """What to add to the reported equity from each ``ts_event`` (in nanoseconds)
        on, as ``amount`` of ``currency``, until the next row of that currency."""
        ...


class NativeEquity(EquityConvention):
    """The equity nautilus reports is true."""

    def corrections(self, cache: Cache) -> pd.DataFrame:
        del cache
        return pd.DataFrame(columns=CORRECTION_COLUMNS)


@dataclass(frozen=True)
class QuoteJob:
    """What a run's quotes are made from: the ``catalog`` holds the data of the
    ``instruments`` over ``window``, and ``venue`` holds the venue arguments."""

    catalog: Path
    instruments: Sequence[InstrumentId]
    window: tuple[datetime, datetime]
    venue: Mapping[str, Any]


class QuoteConvention(ABC):
    """Whether the venue's quotes are made from other data at run time."""

    @abstractmethod
    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        """The venue arguments with the quote settings filled in with their
        defaults; ``ValueError`` when the settings are invalid."""
        ...

    @abstractmethod
    def unmakeable(self, inputs: Sequence[BarSpecification]) -> list[BarSpecification]:
        """The declared bars the venue's data cannot build."""
        ...

    @abstractmethod
    def source_types(self, kinds: set[type]) -> set[type]:
        """The catalog data types a run needing ``kinds`` of data reads."""
        ...

    @abstractmethod
    def write(self, job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
        """Make the run's quotes into a catalog in ``folder``, and return the data
        configs that stream them; none when the catalog's own quotes are used."""
        ...


class NoQuotes(QuoteConvention):
    """The venue streams the quotes the catalog holds."""

    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        if "quotes" in venue:
            raise ValueError("this asset class takes no quotes setting")
        return dict(venue)

    def unmakeable(self, inputs: Sequence[BarSpecification]) -> list[BarSpecification]:
        del inputs
        return []

    def source_types(self, kinds: set[type]) -> set[type]:
        return kinds

    def write(self, job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
        del job, folder
        return []


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
    equity: EquityConvention = field(default_factory=NativeEquity)
    quotes: QuoteConvention = field(default_factory=NoQuotes)

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
