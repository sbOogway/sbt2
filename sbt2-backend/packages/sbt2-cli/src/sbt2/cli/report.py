from pathlib import Path
from typing import Annotated

import pandas as pd
import typer

from sbt2.cli import tables
from sbt2.cli.options import data_option, failing, logger
from sbt2.core import data, results
from sbt2.core.config import Root
from sbt2.core.results import Benchmark, StoredRun

PARTS_HEADER = ("part", "run_id", "start", "end", *tables.HEADLINE)

app = typer.Typer(no_args_is_help=True, help="Report on stored runs.")


@app.command("tearsheet")
def report_tearsheet(
    run_id: Annotated[str, typer.Argument(help="The run's id.")],
    data_root: Annotated[Path, data_option("Reads PATH/results and PATH/catalog.")],
    benchmark: Annotated[
        str | None,
        typer.Option(
            metavar="NAME[:ARG]",
            help="buy-and-hold[:INSTRUMENT], equal-weight, external:FILE or none. "
            "Default: the strategy's.",
        ),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(help="Default: tearsheet.html in the run's folder."),
    ] = None,
) -> None:
    """Write a run's tearsheet, against a benchmark."""
    root = Root(data_root)
    with failing("tearsheet of run %s", run_id):
        store = results.store_at(root)
        stored = store.stored_run(run_id)
        path = output or store.folder(run_id) / "tearsheet.html"
        priced = stored.priced(data.Catalog(root.catalog))
        results.tearsheet(priced, path, _benchmark(benchmark, stored))
    logger.info("wrote the tearsheet of run %s to %s", run_id, path)


def _benchmark(option: str | None, stored: StoredRun) -> Benchmark | None:
    """The benchmark ``NAME[:ARG]`` names, the strategy's own without one."""
    if option is None:
        return stored.benchmark()
    name, _, argument = option.partition(":")
    return stored.benchmark(name, argument or None)


@app.command("parts")
def report_parts(
    run_id: Annotated[str, typer.Argument(help="The run's id.")],
    data_root: Annotated[Path, data_option("Reads PATH/results.")],
) -> None:
    """Show each part a run's parameters were run on, then how the headline
    metrics change from one part to the next."""
    with failing("comparing the parts of run %s", run_id):
        parts = results.compare_parts(results.store_at(Root(data_root)), run_id)
        change = results.degradation(parts)
    typer.echo(f"{_parts_table(parts)}\n\n{_change_table(change)}")


def _parts_table(parts: pd.DataFrame) -> str:
    return tables.frame_table(parts.reset_index(), PARTS_HEADER)


def _change_table(change: pd.DataFrame) -> str:
    """One row per headline metric, one column per part and per change."""
    rows = change.rename_axis("metric").reset_index()
    return tables.frame_table(rows, ("metric", *(str(each) for each in change.columns)))


@app.command("batch")
def report_batch(
    batch_id: Annotated[str, typer.Argument(help="The batch's id.")],
    data_root: Annotated[Path, data_option("Reads PATH/results.")],
) -> None:
    """Show one row per run of a batch: the parameters that vary across it,
    then the headline metrics."""
    with failing("reporting batch %s", batch_id):
        table = results.batch_table(results.store_at(Root(data_root)), batch_id)
    columns = ("run_id", *(str(each) for each in table.columns))
    typer.echo(tables.frame_table(table.reset_index(), columns))


@app.command("study")
def report_study(
    name: Annotated[str, typer.Argument(help="The study's name.")],
    data_root: Annotated[Path, data_option("Reads PATH/results.")],
) -> None:
    """Show one table per part of a study's runs, a row per run: the parameters
    that vary across the study, then the headline metrics."""
    with failing("reporting study %s", name):
        table = results.study_table(
            results.store_at(Root(data_root)), name
        ).reset_index()
    columns = tuple(str(each) for each in table.columns if each != "part")
    typer.echo(tables.part_tables(table, columns))
