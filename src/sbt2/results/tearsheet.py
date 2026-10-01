from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import pandas as pd
from nautilus_trader.analysis import (
    GridLayout,
    TearsheetConfig,
    TearsheetDistributionChart,
    TearsheetDrawdownChart,
    TearsheetEquityChart,
    TearsheetMonthlyReturnsChart,
    TearsheetStatsTableChart,
    TearsheetYearlyReturnsChart,
    create_tearsheet_from_stats,
)

from sbt2.results.benchmarks import Benchmark
from sbt2.results.costs import CostsAndExposure, costs_and_exposure
from sbt2.results.metrics import (
    FullMetrics,
    Segment,
    benchmark_statistics,
    compounded_daily,
    daily_returns,
    full_metrics,
)
from sbt2.results.panels import cost_waterfall, instrument_breakdown, rolling_sharpe
from sbt2.results.pricing import PricedRun

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
        config=_config(sheet),
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
    def costs(self) -> CostsAndExposure:
        return costs_and_exposure(self.run)

    @cached_property
    def returns(self) -> pd.Series:
        return daily_returns(self.run.tables, self.segment)

    @cached_property
    def benchmark_returns(self) -> pd.Series | None:
        if self.benchmark is None:
            return None
        return compounded_daily(self.benchmark.returns(self.run))

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

    @property
    def instrument_rows(self) -> pd.DataFrame:
        """Each traded instrument's costs, activity and trade statistics."""
        trades = _fill_counts(self.run.tables.fills)
        pnls = self.metrics.pnls_by_instrument
        rows = {
            instrument: [
                activity.costs.net,
                activity.costs.fees,
                activity.costs.carry,
                activity.turnover,
                activity.exposure.time_in_market,
                trades[instrument],
                pnls.get(instrument, {}).get("Win Rate"),
            ]
            for instrument, activity in self.costs.by_instrument.items()
        }
        return pd.DataFrame.from_dict(
            rows, orient="index", columns=_INSTRUMENT_COLUMNS, dtype=object
        )


def _fill_counts(fills: pd.DataFrame) -> dict[str, int]:
    if fills.empty:
        return {}
    counts = fills["instrument_id"].astype(str).value_counts()
    return {str(instrument): int(count) for instrument, count in counts.items()}


_INSTRUMENT_COLUMNS = [
    "Net PnL",
    "Fees",
    "Carry",
    "Turnover",
    "Time in Market",
    "Trades",
    "Win Rate",
]


def _config(sheet: _Sheet) -> TearsheetConfig:
    spec = sheet.run.spec
    return TearsheetConfig(
        charts=[
            TearsheetStatsTableChart(),
            TearsheetEquityChart(),
            TearsheetDrawdownChart(),
            TearsheetMonthlyReturnsChart(),
            TearsheetDistributionChart(),
            rolling_sharpe(spec.asset.days_per_year),
            TearsheetYearlyReturnsChart(),
            cost_waterfall(sheet.costs.total.costs),
            instrument_breakdown(sheet.instrument_rows),
        ],
        layout=GridLayout(
            rows=5,
            cols=2,
            heights=[0.32, 0.17, 0.17, 0.17, 0.17],
            vertical_spacing=0.06,
        ),
        title=f"{spec.strategy.strategy}, {spec.part}",
        height=2200,
    )
