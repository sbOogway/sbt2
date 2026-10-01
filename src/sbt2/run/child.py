"""A batch's child process, which runs one backtest.

The parent writes the child's order to stdin as one JSON document. It carries the
parent's ``sys.path``, which must be in place before the spec can import the
strategy's own classes.
"""

import json
import logging
import sys
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Any

from nautilus_trader.common import LogLevel

from sbt2.data import Gap
from sbt2.results import ResultStore, RunIds, open_store
from sbt2.run.execute import RunSettings, execute
from sbt2.spec import ResolvedRunSpec

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

type Document = dict[str, Any]


@dataclass(frozen=True)
class Order:
    run_id: str
    batch_id: str
    spec: ResolvedRunSpec
    known_gaps: tuple[Gap, ...]
    store: ResultStore
    settings: RunSettings
    error_file: Path


def send(order: Order, stream: IO[bytes]) -> None:
    stream.write(json.dumps(_order_document(order)).encode())


def run_child(stream: IO[bytes]) -> None:
    """Run the order sent on ``stream``."""
    _run(_receive(stream))


def _receive(stream: IO[bytes]) -> Order:
    document = json.load(stream)
    sys.path[:] = document["sys_path"]
    return _order(document)


def _order_document(order: Order) -> Document:
    return {
        "run_id": order.run_id,
        "batch_id": order.batch_id,
        "sys_path": sys.path,
        "spec": _spec_document(order.spec),
        "known_gaps": [str(each) for each in order.known_gaps],
        "store": order.store.locator(),
        "settings": _settings_document(order.settings),
        "error_file": str(order.error_file),
    }


def _order(document: Document) -> Order:
    return Order(
        document["run_id"],
        document["batch_id"],
        _spec(document["spec"]),
        tuple(Gap.from_str(each) for each in document["known_gaps"]),
        open_store(document["store"]),
        _settings(document["settings"]),
        Path(document["error_file"]),
    )


def _spec_document(spec: ResolvedRunSpec) -> Document:
    """The spec's hashed document, with the source it leaves out."""
    return {"document": json.loads(spec.to_json()), "source": spec.source}


def _spec(document: Document) -> ResolvedRunSpec:
    spec = ResolvedRunSpec.from_document(document["document"])
    return replace(spec, source=document["source"])


def _settings_document(settings: RunSettings) -> Document:
    return {
        "catalog": str(settings.catalog),
        "chunk_size": settings.chunk_size,
        "log_level": settings.log_level.name,
    }


def _settings(document: Document) -> RunSettings:
    return RunSettings(
        Path(document["catalog"]),
        document["chunk_size"],
        LogLevel.from_str(document["log_level"]),
    )


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
