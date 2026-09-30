from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import pandas as pd
from nautilus_trader.analysis import (
    TearsheetConfig,
    TearsheetDistributionChart,
    TearsheetDrawdownChart,
    TearsheetEquityChart,
    TearsheetMonthlyReturnsChart,
    TearsheetRollingSharpeChart,
    TearsheetStatsTableChart,
    TearsheetYearlyReturnsChart,
    create_tearsheet_from_stats,
)

from sbt2.results.costs import PricedRun
from sbt2.results.metrics import FullMetrics, Segment, daily_returns, full_metrics

type Statistics = dict[str, float | None]


def tearsheet(run: PricedRun, path: Path) -> None:
    """Nautilus's tearsheet of the run over its part, written to ``path`` in
    the format its extension names.

    Its panels plot the run's equity returns compounded to daily ones, which
    nautilus's panels assume; its statistics are the run's full metrics.
    """
    sheet = _Sheet(run)
    create_tearsheet_from_stats(
        sheet.pnl_statistics,
        sheet.metrics.returns,
        sheet.general_statistics,
        sheet.returns,
        output_path=str(path),
        config=_config(run),
    )


@dataclass(frozen=True)
class _Sheet:
    run: PricedRun

    @cached_property
    def segment(self) -> Segment:
        return Segment.of_run(self.run.spec)

    @cached_property
    def metrics(self) -> FullMetrics:
        return full_metrics(self.run.tables, self.segment)

    @cached_property
    def returns(self) -> pd.Series:
        return daily_returns(self.run.tables, self.segment)

    @property
    def pnl_statistics(self) -> dict[str, Statistics]:
        return {self.run.tables.currency: self.metrics.pnls}

    @property
    def general_statistics(self) -> Statistics:
        return {
            **self.metrics.general,
            "Probabilistic Sharpe Ratio": self.metrics.probabilistic_sharpe,
        }


def _config(run: PricedRun) -> TearsheetConfig:
    return TearsheetConfig(
        charts=[
            TearsheetStatsTableChart(),
            TearsheetEquityChart(),
            TearsheetDrawdownChart(),
            TearsheetMonthlyReturnsChart(),
            TearsheetDistributionChart(),
            TearsheetRollingSharpeChart(),
            TearsheetYearlyReturnsChart(),
        ],
        title=f"{run.spec.strategy.strategy}, {run.spec.part}",
    )
