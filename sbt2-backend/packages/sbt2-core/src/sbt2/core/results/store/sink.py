from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import pandas as pd
from nautilus_trader.model import PortfolioSnapshot, PositionAdjusted

from sbt2.core.market import Rates


@dataclass(frozen=True)
class Reports:
    """Nautilus's own reports, as its ``ReportProvider`` returns them.

    ``index_prices`` are the index prices by time of the underlying of each
    option contract, by instrument id, which value the trades in USD.
    ``portfolio_greeks`` holds the sampled ``ts_event`` (ns), ``theta``,
    ``theta_ratio`` and ``beta_weighted_delta`` of a run with an option chain.
    ``refusals`` holds the ``ts_event`` (ns), ``legs`` (instrument ids) and
    ``reason`` of each combo the short premium rules refused."""

    fills: pd.DataFrame
    positions: pd.DataFrame
    account: pd.DataFrame
    orders: pd.DataFrame | None = None
    index_prices: Mapping[str, pd.Series] | None = None
    portfolio_greeks: pd.DataFrame | None = None
    refusals: pd.DataFrame | None = None


class OutputSink(Protocol):
    """Where one run's output goes, called once at the end of the run."""

    @property
    def run_id(self) -> str: ...

    def use_rates(self, rates: Rates) -> None:
        """Convert the amounts of the other currencies of the run into its
        reporting currency with ``rates``, in what is written after. A run in one
        currency does not call it."""
        ...

    def write_equity(
        self,
        snapshots: Sequence[PortfolioSnapshot],
        corrections: pd.DataFrame | None = None,
    ) -> None:
        """Store the equity of the snapshots.

        ``corrections`` hold ``ts_event``, ``currency`` and ``amount``: what to add
        to the equity of a snapshot after ``ts_event``, until the next row.
        """
        ...

    def write_margin(self, margin: pd.DataFrame) -> None:
        """Store the margin the run's positions reserved: ``ts_event`` in
        nanoseconds, the equity's times, ``currency``, ``margin_used`` and
        ``maintenance_margin``. A run without a margin model does not call it."""
        ...

    def write_carry(self, adjustments: Sequence[PositionAdjusted]) -> None: ...

    def write_reports(self, reports: Reports) -> None: ...

    def write_strategy_source(self, source: str) -> None:
        """Keep the source of the strategy's module with the run."""
        ...

    def write_drawdown_trip(self, tripped_at: datetime) -> None:
        """Record when the drawdown guard stopped the run's trading.

        A run whose guard never trips does not call it.
        """
        ...

    def finalize(self) -> None:
        """Compute the headline metrics and write the run's summary, last."""
        ...


class IncompleteRunError(RuntimeError):
    pass
