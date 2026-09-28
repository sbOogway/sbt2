import logging
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from nautilus_trader.common import LogLevel

from sbt2 import spec
from sbt2.results import ParquetResultStore, Provenance
from sbt2.run import RunSettings, execute

DATA = Path("data")
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
logger = logging.getLogger("sbt2")


class Level(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@app.callback()
def main(
    context: typer.Context,
    log_level: Annotated[
        Level, typer.Option(help="For sbt2 and nautilus.")
    ] = Level.INFO,
    log_file: Annotated[Path | None, typer.Option(help="Also log here.")] = None,
) -> None:
    """Backtesting on nautilus_trader."""
    _configure_logging(log_level, log_file)
    context.obj = log_level


@app.command()
def run(
    context: typer.Context,
    spec_file: Annotated[Path, typer.Argument(help="The run spec, a TOML file.")],
    data: Annotated[Path, typer.Option(help="Holds catalog/ and results/.")] = DATA,
) -> None:
    """Run the backtest a spec file describes and store its result."""
    try:
        _run(spec_file, data, LogLevel.from_str(context.obj))
    except Exception:
        logger.exception("run of %s failed", spec_file)
        raise typer.Exit(1) from None


def _run(spec_file: Path, data: Path, log_level: LogLevel) -> None:
    resolved = spec.load(spec_file)
    store = ParquetResultStore(data / "results")
    sink = store.new_run(resolved, Provenance.of_repo(Path.cwd()))
    execute(resolved, sink, RunSettings(data / "catalog", log_level=log_level))
    logger.info("stored run %s in %s", sink.run_id, data / "results")


def _configure_logging(level: Level, log_file: Path | None) -> None:
    """Configures the ``sbt2`` logger only, so it never clobbers the host's."""
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file is not None:
        handlers.append(logging.FileHandler(log_file))
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    for handler in handlers:
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)
    logger.setLevel(level)
