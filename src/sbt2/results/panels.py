"""sbt2's tearsheet panels, drawn by nautilus's tearsheet into its grid.

Nautilus calls each renderer with the figure, the panel's cell and keyword
arguments: its own, such as ``returns`` and ``theme_config``, and the panel's.
"""

import math
from dataclasses import astuple
from typing import Any

import pandas as pd
import plotly.graph_objects as go
from nautilus_trader.analysis import (
    TearsheetChart,
    TearsheetCustomChart,
    register_tearsheet_chart,
)

from sbt2.results.costs import CostWaterfall

_COST_WATERFALL = "sbt2_cost_waterfall"
_ROLLING_SHARPE = "sbt2_rolling_sharpe"
_ROLLING_WINDOW = 60


def rolling_sharpe(days_per_year: int) -> TearsheetChart:
    """The Sharpe ratio over the last 60 daily returns, annualized by the
    asset's calendar where nautilus's own takes 252 days."""
    return TearsheetCustomChart(
        chart=_ROLLING_SHARPE, args={"days_per_year": days_per_year}
    )


def cost_waterfall(costs: CostWaterfall) -> TearsheetChart:
    """The run's gross PnL, its fees and carry, and the net PnL they leave."""
    return TearsheetCustomChart(chart=_COST_WATERFALL, args={"costs": costs})


def _draw_rolling_sharpe(fig: go.Figure, row: int, col: int, **panel: Any) -> None:
    returns: pd.Series = panel["returns"]
    if len(returns) < _ROLLING_WINDOW:
        return
    rolling = returns.rolling(_ROLLING_WINDOW)
    volatility = pd.Series(rolling.std()).replace(0, math.nan)
    sharpe = pd.Series(rolling.mean() / volatility) * math.sqrt(panel["days_per_year"])
    colors = panel["theme_config"]["colors"]
    fig.add_trace(
        go.Scatter(
            x=sharpe.index,
            y=sharpe.to_numpy(),
            mode="lines",
            name="Rolling Sharpe",
            line={"color": colors["positive"], "width": 2},
            showlegend=False,
        ),
        row=row,
        col=col,
    )
    fig.update_xaxes(title_text="Date", row=row, col=col)
    fig.update_yaxes(title_text="Sharpe Ratio", row=row, col=col)


def _draw_cost_waterfall(fig: go.Figure, row: int, col: int, **panel: Any) -> None:
    colors = panel["theme_config"]["colors"]
    fig.add_trace(
        go.Waterfall(
            x=["Gross PnL", "Fees", "Carry", "Net PnL"],
            y=list(astuple(panel["costs"])),
            measure=["absolute", "relative", "relative", "total"],
            increasing={"marker": {"color": colors["positive"]}},
            decreasing={"marker": {"color": colors["negative"]}},
            totals={"marker": {"color": colors["primary"]}},
            showlegend=False,
        ),
        row=row,
        col=col,
    )
    fig.update_yaxes(title_text="PnL", row=row, col=col)


register_tearsheet_chart(
    _COST_WATERFALL, "waterfall", "Cost Waterfall", _draw_cost_waterfall
)
register_tearsheet_chart(
    _ROLLING_SHARPE,
    "scatter",
    f"Rolling Sharpe Ratio ({_ROLLING_WINDOW}-day)",
    _draw_rolling_sharpe,
)
