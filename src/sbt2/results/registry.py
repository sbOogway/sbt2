from collections.abc import Mapping
from typing import Any

from sbt2.results.parquet import ParquetResultStore
from sbt2.results.store import ResultStore

_STORES: tuple[type[ResultStore], ...] = (ParquetResultStore,)


class UnknownStoreError(LookupError):
    pass


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
