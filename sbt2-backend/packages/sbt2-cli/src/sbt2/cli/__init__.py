import logging
import sys
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer

from sbt2.cli import data, download, ingest, report, run, runs, studies
from sbt2.cli.options import logger

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

__all__ = ["app"]


class Level(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(run.app)
app.add_typer(download.app)
app.add_typer(ingest.app)
app.add_typer(data.app, name="data")
app.add_typer(runs.app, name="runs")
app.add_typer(report.app, name="report")
app.add_typer(studies.app, name="studies")


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
