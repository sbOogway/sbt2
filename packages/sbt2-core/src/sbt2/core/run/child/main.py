"""A batch's child process, which runs one backtest."""

import logging
import traceback
from multiprocessing.connection import Connection

from sbt2.core.results import RunIds
from sbt2.core.run.child.order import Order, receive
from sbt2.core.run.execute import execute

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def run_child(pipe: Connection) -> None:
    """Run the order sent on ``pipe``."""
    _run(receive(pipe))


def _run(order: Order) -> None:
    logging.basicConfig(format=LOG_FORMAT, level=order.settings.log_level.name)
    try:
        ids = RunIds(order.run_id, order.batch_id)
        sink = order.store.new_run(order.spec, order.known_gaps, ids)
        execute(order.spec, sink, order.settings)
    except BaseException as error:
        order.error_file.write_text(_described(error))
        raise


def _described(error: BaseException) -> str:
    return "".join(traceback.format_exception_only(error)).strip()
