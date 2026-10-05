import logging
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import typer

DAY = ["%Y-%m-%d"]
DATA_ROOT_ENV = "SBT2_DATA"
CONFIG_ENV = "SBT2_CONFIG"

logger = logging.getLogger("sbt2")


def data_option(help_text: str) -> Any:
    return typer.Option(
        "--data", envvar=DATA_ROOT_ENV, show_envvar=True, help=help_text
    )


@contextmanager
def failing(action: str, *args: object) -> Generator[None]:
    """Logs an exception as the action failing, and exits with code 1."""
    try:
        yield
    except Exception:
        logger.exception("%s failed", action % args)
        raise typer.Exit(1) from None
