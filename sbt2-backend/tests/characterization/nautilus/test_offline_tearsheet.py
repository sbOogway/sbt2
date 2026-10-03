import inspect
import math
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
from nautilus_trader.analysis import (
    TearsheetConfig,
    TearsheetCustomChart,
    TearsheetStatsTableChart,
    create_tearsheet_from_stats,
    register_chart,
    register_tearsheet_chart,
)
from plotted import plotted

DAYS = pd.date_range("2024-01-01", periods=100, freq="D", tz="UTC")
RETURNS = pd.Series(np.sin(np.arange(100)) / 100 + 0.001, index=DAYS)
PNLS = {"Win Rate": 0.5}
STATS_RETURNS = {"Sharpe Ratio (252 days)": 1.25}
GENERAL = {"Long Ratio": 0.75}
DEFAULT_PANELS = [
    "Performance Statistics",
    "Equity Curve",
    "Drawdown",
    "Monthly Returns",
    "Returns Distribution",
    "Rolling Sharpe Ratio (60-day)",
    "Yearly Returns",
]


def tearsheet(**options: Any) -> str:
    html = create_tearsheet_from_stats(
        PNLS, STATS_RETURNS, GENERAL, RETURNS, output_path=None, **options
    )
    assert html is not None
    return html


@pytest.mark.unit
@pytest.mark.characterization
def test_an_offline_tearsheet_needs_only_stats_and_returns() -> None:
    html = tearsheet()

    for name in ("Win Rate", "Sharpe Ratio (252 days)", "Long Ratio"):
        assert name in html
    assert plotted(html).titles == DEFAULT_PANELS


@pytest.mark.unit
@pytest.mark.characterization
def test_the_benchmark_is_overlaid_under_its_name() -> None:
    benchmark = pd.Series(0.002, index=DAYS)

    figure = plotted(
        tearsheet(benchmark_returns=benchmark, benchmark_name="Buy and hold")
    )

    overlay = figure.trace("Buy and hold")
    assert overlay["xaxis"] == figure.trace("Strategy")["xaxis"]
    assert overlay["y"][-1] == pytest.approx(1.002**100)


@pytest.mark.unit
@pytest.mark.characterization
def test_a_registered_tearsheet_chart_draws_in_its_own_panel() -> None:
    calls: list[dict[str, Any]] = []

    def probe(fig: go.Figure, row: int, col: int, **kwargs: Any) -> None:
        calls.append({"row": row, "col": col, **kwargs})
        fig.add_trace(go.Bar(name="Probe bars", x=["a"], y=[1.0]), row=row, col=col)

    register_tearsheet_chart("sbt2_probe", "bar", "Probe panel", probe)
    config = TearsheetConfig(
        charts=[TearsheetStatsTableChart(), TearsheetCustomChart(chart="sbt2_probe")]
    )

    figure = plotted(tearsheet(config=config))

    [call] = calls
    assert (call["row"], call["col"]) == (1, 2)
    assert call["stats_returns"] == STATS_RETURNS
    assert call["stats_general"] == GENERAL
    assert call["stats_pnls"] == PNLS
    assert figure.named("Probe bars")
    assert figure.titles == ["Performance Statistics", "Probe panel"]


@pytest.mark.unit
@pytest.mark.characterization
def test_a_register_chart_figure_cannot_be_placed_in_the_tearsheet() -> None:
    register_chart("sbt2_standalone", lambda _returns: go.Figure())
    config = TearsheetConfig(charts=[TearsheetCustomChart(chart="sbt2_standalone")])

    with pytest.raises(KeyError, match="No tearsheet chart registered"):
        tearsheet(config=config)


@pytest.mark.unit
@pytest.mark.characterization
def test_the_offline_tearsheet_takes_no_period() -> None:
    parameters = inspect.signature(create_tearsheet_from_stats).parameters

    assert "period" not in parameters


@pytest.mark.unit
@pytest.mark.characterization
def test_nautilus_rolling_sharpe_is_annualized_at_252_days() -> None:
    rolling = RETURNS.rolling(60)
    expected = pd.Series(rolling.mean() / rolling.std()).dropna() * math.sqrt(252)

    sharpe = plotted(tearsheet()).trace("Rolling Sharpe")["y"]

    assert list(sharpe[~np.isnan(sharpe)]) == pytest.approx(list(expected))
