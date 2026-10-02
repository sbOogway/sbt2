from collections.abc import Mapping
from typing import Any

from sbt2.core.config import Root
from sbt2.core.results.store.base import (
    MissingTableError,
    ResultStore,
    RunFilter,
    RunIds,
    StoredRun,
    StoredStudy,
    Table,
    UnknownRunError,
    UnknownStudyError,
)
from sbt2.core.results.store.parquet import ParquetResultStore
from sbt2.core.results.store.sink import IncompleteRunError, OutputSink, Reports

_STORES: tuple[type[ResultStore], ...] = (ParquetResultStore,)


class UnknownStoreError(LookupError):
    pass


def store_at(root: Root) -> ResultStore:
    """The store holding the runs under ``root``."""
    return ParquetResultStore(root.results)


def open_store(locator: Mapping[str, Any]) -> ResultStore:
    """The store ``locator`` describes, as ``ResultStore.locator`` wrote it."""
    location = {key: value for key, value in locator.items() if key != "kind"}
    return _store_class(locator["kind"]).from_location(location)


def _store_class(kind: str) -> type[ResultStore]:
    for each in _STORES:
        if each.kind == kind:
            return each
    known = ", ".join(sorted(each.kind for each in _STORES))
    raise UnknownStoreError(f"no result store {kind}; known: {known}")


__all__ = [
    "IncompleteRunError",
    "MissingTableError",
    "OutputSink",
    "ParquetResultStore",
    "Reports",
    "ResultStore",
    "RunFilter",
    "RunIds",
    "StoredRun",
    "StoredStudy",
    "Table",
    "UnknownRunError",
    "UnknownStoreError",
    "UnknownStudyError",
    "open_store",
    "store_at",
]
