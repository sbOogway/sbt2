"""A batch's child process, which runs one backtest.

The parent writes two pickles to stdin: its ``sys.path``, which must be in place
before the second can load the strategy's own classes, then the child's order.
"""

import logging
import pickle
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from sbt2.data import Gap
from sbt2.results import ResultStore
from sbt2.run.execute import RunSettings, execute
from sbt2.spec import ResolvedRunSpec

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


@dataclass(frozen=True)
class Order:
    run_id: str
    spec: ResolvedRunSpec
    known_gaps: tuple[Gap, ...]
    store: ResultStore
    settings: RunSettings
    error_file: Path


def send(order: Order, stream: IO[bytes]) -> None:
    pickle.dump(sys.path, stream)
    pickle.dump(order, stream)


def run_child(stream: IO[bytes]) -> None:
    """Run the order sent on ``stream``."""
    _run(_receive(stream))


def _receive(stream: IO[bytes]) -> Order:
    sys.path[:] = pickle.load(stream)
    return pickle.load(stream)


def _run(order: Order) -> None:
    logging.basicConfig(format=LOG_FORMAT, level=order.settings.log_level.name)
    try:
        sink = order.store.new_run(order.spec, order.known_gaps, order.run_id)
        execute(order.spec, sink, order.settings)
    except BaseException as error:
        order.error_file.write_text(_described(error))
        raise


def _described(error: BaseException) -> str:
    return "".join(traceback.format_exception_only(error)).strip()
