from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import pandas as pd
from nautilus_trader.model import PortfolioSnapshot, PositionAdjusted


@dataclass(frozen=True)
class Reports:
    """Nautilus's own reports, as its ``ReportProvider`` returns them."""

    fills: pd.DataFrame
    positions: pd.DataFrame
    account: pd.DataFrame
    orders: pd.DataFrame | None = None


class OutputSink(Protocol):
    """Where one run's output goes, called once at the end of the run."""

    @property
    def run_id(self) -> str: ...

    def write_equity(self, snapshots: Sequence[PortfolioSnapshot]) -> None: ...

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
