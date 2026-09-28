from collections.abc import Sequence
from dataclasses import dataclass
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

    def finalize(self, benchmark: pd.Series | None = None) -> None:
        """Compute the headline metrics and write the run's summary, last.

        ``benchmark`` is a return series indexed by UTC timestamps.
        """
        ...


class IncompleteRunError(RuntimeError):
    pass
