import json
from pathlib import Path
from typing import Annotated

import numpy as np
import pandas as pd
import typer

from sbt2.cli import tables
from sbt2.cli.options import data_option, failing
from sbt2.core import results
from sbt2.core.config import Root
from sbt2.core.results import MissingTableError, ResultStore

RUNS_HEADER = (
    "run_id",
    "strategy",
    "part",
    "start",
    "end",
    "net_return",
    "sharpe",
    "max_drawdown",
    "trade_count",
)

app = typer.Typer(no_args_is_help=True, help="Query and manage stored runs.")


@app.command("list")
def list_runs(
    data_root: Annotated[Path, data_option("Reads PATH/results.")],
    strategy: Annotated[
        str | None, typer.Option(help="Only this strategy's import path.")
    ] = None,
    part: Annotated[str | None, typer.Option(help="Only this part.")] = None,
) -> None:
    """Show one row per finished run, oldest first."""
    with failing("listing the runs in %s", Root(data_root).results):
        runs = results.store_at(Root(data_root)).runs(
            results.RunFilter(strategy=strategy, part=part)
        )
    typer.echo(_runs_table(runs))


def _runs_table(runs: pd.DataFrame) -> str:
    if runs.empty:
        return "no runs"
    return tables.frame_table(runs, RUNS_HEADER)


@app.command()
def show(
    run_id: Annotated[str, typer.Argument(help="The run's id.")],
    data_root: Annotated[Path, data_option("Reads PATH/results.")],
) -> None:
    """Show a run's summary and its resolved spec."""
    with failing("showing run %s", run_id):
        text = _shown(results.store_at(Root(data_root)), run_id)
    typer.echo(text)


@app.command()
def delete(
    run_id: Annotated[str, typer.Argument(help="The run's id.")],
    data_root: Annotated[Path, data_option("Deletes from PATH/results.")],
    yes: Annotated[bool, typer.Option("--yes", help="Don't ask first.")] = False,
) -> None:
    """Delete a run's folder, a failed run's partial one included."""
    if not yes:
        typer.confirm(f"delete run {run_id}?", abort=True)
    with failing("deleting run %s", run_id):
        results.store_at(Root(data_root)).delete(run_id)


def _shown(store: ResultStore, run_id: str) -> str:
    document = json.dumps(store.spec(run_id), indent=2)
    return f"{_summary_lines(store, run_id)}\n\n{document}"


def _summary_lines(store: ResultStore, run_id: str) -> str:
    try:
        [record] = store.load(run_id, "summary").to_dict("records")
    except MissingTableError:
        return f"run {run_id} has no summary: it did not finish"
    width = max(len(str(column)) for column in record)
    return "\n".join(
        f"{str(column).ljust(width)}  {_detail(value)}"
        for column, value in record.items()
    )


def _detail(value: object) -> str:
    if isinstance(value, np.ndarray):
        return ", ".join(str(each) for each in value) or "-"
    return tables.text(value)
