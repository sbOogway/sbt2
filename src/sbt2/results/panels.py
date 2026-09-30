"""sbt2's tearsheet panels, drawn by nautilus's tearsheet into its grid.

Nautilus calls each renderer with the figure, the panel's cell and keyword
arguments: its own, such as ``returns`` and ``theme_config``, and the panel's.
"""

import math
import numbers
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
_INSTRUMENT_BREAKDOWN = "sbt2_instrument_breakdown"
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


def instrument_breakdown(rows: pd.DataFrame) -> TearsheetChart:
    """A table of ``rows``, one per traded instrument indexed by its id."""
    return TearsheetCustomChart(chart=_INSTRUMENT_BREAKDOWN, args={"rows": rows})


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


def _draw_instrument_breakdown(
    fig: go.Figure, row: int, col: int, **panel: Any
) -> None:
    rows: pd.DataFrame = panel["rows"]
    colors = panel["theme_config"]["colors"]
    fig.add_trace(
        go.Table(
            columnwidth=[3] + [2] * len(rows.columns),
            header={
                "values": [f"<b>{each}</b>" for each in ["Instrument", *rows.columns]],
                "fill_color": colors["primary"],
                "font": {"color": "white", "size": 12},
                "align": "left",
            },
            cells={
                "values": [
                    [str(each) for each in rows.index],
                    *([_cell(each) for each in rows[name]] for name in rows.columns),
                ],
                "align": "left",
                "font": {"size": 11, "color": colors["table_text"]},
            },
        ),
        row=row,
        col=col,
    )


def _cell(value: object) -> str:
    if isinstance(value, numbers.Integral):
        return str(value)
    if isinstance(value, numbers.Real) and math.isfinite(value):
        return f"{value:.4f}"
    return ""


register_tearsheet_chart(
    _COST_WATERFALL, "waterfall", "Cost Waterfall", _draw_cost_waterfall
)
register_tearsheet_chart(
    _INSTRUMENT_BREAKDOWN,
    "table",
    "Instrument Breakdown",
    _draw_instrument_breakdown,
)
register_tearsheet_chart(
    _ROLLING_SHARPE,
    "scatter",
    f"Rolling Sharpe Ratio ({_ROLLING_WINDOW}-day)",
    _draw_rolling_sharpe,
)
