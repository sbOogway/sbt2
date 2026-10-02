"""The order a batch sends each child.

The parent writes the child's order to stdin as one JSON document. It carries the
parent's ``sys.path``, which must be in place before the spec can import the
strategy's own classes.
"""

import json
import sys
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import IO, Any

from nautilus_trader.common import LogLevel

from sbt2.core.data import Gap
from sbt2.core.results import ResultStore, open_store
from sbt2.core.run.execute import RunSettings
from sbt2.core.spec import ResolvedRunSpec, Study

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


def receive(stream: IO[bytes]) -> Order:
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
    """The spec's hashed document, with the source and study it leaves out."""
    return {
        "document": json.loads(spec.to_json()),
        "source": spec.source,
        "study": None if spec.study is None else asdict(spec.study),
    }


def _spec(document: Document) -> ResolvedRunSpec:
    spec = ResolvedRunSpec.from_document(document["document"])
    study = document["study"]
    return replace(spec, source=document["source"], study=study and Study(**study))


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
