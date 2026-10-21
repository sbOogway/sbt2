from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from nautilus_trader.backtest import BacktestDataConfig
from nautilus_trader.model import BarSpecification, InstrumentId


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
    def source_types(self, kinds: set[type], venue: Mapping[str, Any]) -> set[type]:
        """The catalog data types a run needing ``kinds`` of data reads on the
        venue with the arguments ``venue``."""
        ...

    @abstractmethod
    def write(self, job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
        """Make the run's quotes into a catalog in ``folder``, and return the data
        configs that stream them; none when the catalog's own quotes are used."""
        ...

    def priced_from(self, price_type: type, venue: Mapping[str, Any]) -> type:
        """The catalog data type a stored run's ``price_type`` prices are read
        from; by default the type itself."""
        del venue
        return price_type


class NoQuotes(QuoteConvention):
    """The venue streams the quotes the catalog holds."""

    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        if "quotes" in venue:
            raise ValueError("this asset class takes no quotes setting")
        return dict(venue)

    def unmakeable(self, inputs: Sequence[BarSpecification]) -> list[BarSpecification]:
        del inputs
        return []

    def source_types(self, kinds: set[type], venue: Mapping[str, Any]) -> set[type]:
        del venue
        return kinds

    def write(self, job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
        del job, folder
        return []
