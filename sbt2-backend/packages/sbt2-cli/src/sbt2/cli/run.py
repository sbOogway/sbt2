import re
from pathlib import Path
from typing import Annotated

import typer
from nautilus_trader.common import LogLevel

from sbt2.cli import progress, tables
from sbt2.cli.options import CONFIG_ENV, data_option, failing, logger
from sbt2.core import results, spec
from sbt2.core.config import ConfigFolder, Root
from sbt2.core.results import ResultStore
from sbt2.core.run import (
    BatchSetup,
    Launch,
    Memory,
    batch,
    launcher_named,
)

SIZE = re.compile(r"(\d+)([KMGT]?)")
SIZE_UNITS = {"": 0, "K": 10, "M": 20, "G": 30, "T": 40}
HEADLINE_HEADER = ("run_id", "strategy", *tables.HEADLINE)

app = typer.Typer()


def _size(text: str) -> int:
    """Bytes, from a size in systemd's syntax such as ``512M`` or ``4G``."""
    match = SIZE.fullmatch(text)
    if match is None:
        raise ValueError(f"{text} is not a size such as 512M or 4G")
    number, unit = match.groups()
    return int(number) * 2 ** SIZE_UNITS[unit]


@app.command()
def run(
    context: typer.Context,
    spec_file: Annotated[Path, typer.Argument(help="The run spec, a TOML file.")],
    data: Annotated[
        Path, data_option("Holds raw/, catalog/, results/ and known_gaps.toml.")
    ],
    config: Annotated[
        Path,
        typer.Option(
            envvar=CONFIG_ENV,
            show_envvar=True,
            help="The config folder; reads PATH/venues.toml.",
        ),
    ],
    memory_budget: Annotated[
        int | None,
        typer.Option(
            parser=_size,
            metavar="SIZE",
            help="Memory for all the runs at once. Default: half the machine's.",
        ),
    ] = None,
    memory_per_run: Annotated[
        int | None,
        typer.Option(
            parser=_size,
            metavar="SIZE",
            help="The memory cap of each run, e.g. 4G, enforced only by "
            "--launcher systemd. Default: 4G.",
        ),
    ] = None,
    launcher: Annotated[
        str,
        typer.Option(
            help="uncapped leaves each run's memory to the machine or container; "
            "systemd caps each run in its own systemd scope.",
        ),
    ] = "uncapped",
) -> None:
    """Run the backtests a spec file describes and store their results."""
    with failing("run of %s", spec_file):
        root = Root(data.resolve())
        level = LogLevel.from_str(context.obj)
        memory = _memory(memory_budget, memory_per_run)
        launch = Launch(launcher_named(launcher), memory)
        runs = spec.load(spec_file, ConfigFolder(config.resolve()).venues)
        _run(runs, BatchSetup.at(root, launch, level))


def _memory(budget: int | None, per_run: int | None) -> Memory:
    return Memory(budget) if per_run is None else Memory(budget, per_run)


def _run(runs: list[spec.ResolvedRunSpec], setup: BatchSetup) -> None:
    """Pre-flight every run, then execute them in a batch."""
    with progress.runs_bar() as bar:
        run_ids = batch(runs, setup, bar)
    for run_id in run_ids:
        logger.info("stored run %s in %s", run_id, setup.store.folder(run_id))
    typer.echo(_headline_tables(setup.store, run_ids))


def _headline_tables(store: ResultStore, run_ids: tuple[str, ...]) -> str:
    """One table of the runs' headline metrics per part, in split order."""
    runs = store.runs(results.RunFilter(run_ids=run_ids))
    return tables.part_tables(runs, HEADLINE_HEADER)
