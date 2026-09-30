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

from sbt2.results.benchmarks import Benchmark
from sbt2.results.costs import PricedRun
from sbt2.results.metrics import (
    FullMetrics,
    Segment,
    benchmark_statistics,
    compounded_daily,
    daily_returns,
    full_metrics,
)

type Statistics = dict[str, float | None]


def tearsheet(run: PricedRun, path: Path, benchmark: Benchmark | None = None) -> None:
    """Nautilus's tearsheet of the run over its part, written to ``path`` in
    the format its extension names.

    Its panels plot the run's equity returns compounded to daily ones, which
    nautilus's panels assume; its statistics are the run's full metrics, with
    the statistics relative to ``benchmark``, which is overlaid when given.
    """
    sheet = _Sheet(run, benchmark)
    create_tearsheet_from_stats(
        sheet.pnl_statistics,
        sheet.return_statistics,
        sheet.general_statistics,
        sheet.returns,
        output_path=str(path),
        config=_config(run),
        benchmark_returns=sheet.benchmark_returns,
        benchmark_name=sheet.benchmark_name,
    )


@dataclass(frozen=True)
class _Sheet:
    run: PricedRun
    benchmark: Benchmark | None

    @cached_property
    def segment(self) -> Segment:
        return Segment.of_run(self.run.spec)

    @cached_property
    def metrics(self) -> FullMetrics:
        return full_metrics(self.run.tables, self.segment)

    @cached_property
    def returns(self) -> pd.Series:
        return daily_returns(self.run.tables, self.segment)

    @cached_property
    def benchmark_returns(self) -> pd.Series | None:
        if self.benchmark is None:
            return None
        run = self.run
        grid = self.benchmark.returns(run.spec, run.catalog, run.known_gaps)
        return compounded_daily(grid)

    @property
    def benchmark_name(self) -> str:
        return type(self.benchmark).__name__ if self.benchmark else "Benchmark"

    @property
    def pnl_statistics(self) -> dict[str, Statistics]:
        return {self.run.tables.currency: self.metrics.pnls}

    @property
    def return_statistics(self) -> Statistics:
        relative = benchmark_statistics(
            self.returns, self.benchmark_returns, self.segment.days_per_year
        )
        return {**self.metrics.returns, **relative}

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
