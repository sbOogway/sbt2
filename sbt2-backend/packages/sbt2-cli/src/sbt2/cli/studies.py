from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from sbt2.cli import tables
from sbt2.cli.options import data_option, failing
from sbt2.core import results
from sbt2.core.config import Root

app = typer.Typer(no_args_is_help=True, help="Query stored studies.")


@app.command("list")
def list_studies(
    data_root: Annotated[Path, data_option("Reads PATH/results.")],
) -> None:
    """Show one row per study: its strategy and how many runs it holds."""
    with failing("listing the studies in %s", Root(data_root).results):
        studies = results.study_list(results.store_at(Root(data_root)))
    typer.echo(_studies_table(studies))


def _studies_table(studies: pd.DataFrame) -> str:
    if studies.empty:
        return "no studies"
    return tables.frame_table(studies, tuple(str(each) for each in studies.columns))
