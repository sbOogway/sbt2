from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from sbt2.core.data.sources.base import (
    CANDLES,
    Fetch,
    FundingOffGridError,
    Gap,
    MissingAtSourceError,
    RawFile,
    Source,
    UnsupportedDataTypeError,
    candle_type,
)
from sbt2.core.data.sources.bybit import BybitSource
from sbt2.core.tomlfiles import read_toml, write_toml

__all__ = [
    "CANDLES",
    "Fetch",
    "FundingOffGridError",
    "Gap",
    "ListedGap",
    "MissingAtSourceError",
    "RawFile",
    "Source",
    "UnknownSourceError",
    "UnsupportedDataTypeError",
    "add_known_gaps",
    "candle_type",
    "known_gaps",
    "listed_gaps",
    "remove_known_gaps",
    "source",
]

_SOURCES: tuple[type[Source], ...] = (BybitSource,)


class UnknownSourceError(LookupError):
    pass


@dataclass(frozen=True)
class ListedGap:
    """A known gap as the known gaps file lists it; ``data`` names the data type
    as the source's list does."""

    source: str
    symbol: str
    data: str
    day: date


def source(name: str, known_gaps_file: Path) -> Source:
    """The source adapter called ``name``, with the known gaps
    ``known_gaps_file`` lists for it."""
    return _source_class(name).listing(_lists(known_gaps_file).get(name, ()))


def known_gaps(known_gaps_file: Path) -> frozenset[Gap]:
    """The known gaps of every source ``known_gaps_file`` lists; none when the
    file is missing."""
    names = _lists(known_gaps_file)
    return frozenset().union(
        *(source(name, known_gaps_file).known_gaps for name in names)
    )


def listed_gaps(known_gaps_file: Path) -> list[ListedGap]:
    """Every gap ``known_gaps_file`` lists, in its order; none when the file is
    missing."""
    return [
        _listed(name, entry)
        for name, entries in _lists(known_gaps_file).items()
        for entry in entries
    ]


def add_known_gaps(known_gaps_file: Path, gaps: Iterable[ListedGap]) -> None:
    """Append ``gaps`` to their sources' lists, each once; a gap of an unknown
    source or data type raises and leaves the file as it was."""
    lists = _lists(known_gaps_file)
    for gap in gaps:
        entry = _checked_entry(gap)
        entries = lists.setdefault(gap.source, [])
        if entry not in entries:
            entries.append(entry)
    write_toml(known_gaps_file, lists)


def remove_known_gaps(known_gaps_file: Path, gaps: Iterable[ListedGap]) -> None:
    """Drop ``gaps`` from their sources' lists; a gap not listed is skipped."""
    dropped = set(gaps)
    lists = {
        name: [each for each in entries if _listed(name, each) not in dropped]
        for name, entries in _lists(known_gaps_file).items()
    }
    write_toml(known_gaps_file, lists)


def _listed(name: str, entry: Mapping[str, Any]) -> ListedGap:
    return ListedGap(name, entry["symbol"], entry["data"], entry["day"])


def _checked_entry(gap: ListedGap) -> dict[str, Any]:
    entry = {"symbol": gap.symbol, "data": gap.data, "day": gap.day}
    _source_class(gap.source).listing([entry])
    return entry


def _source_class(name: str) -> type[Source]:
    for each in _SOURCES:
        if each.name == name:
            return each
    known = ", ".join(sorted(each.name for each in _SOURCES))
    raise UnknownSourceError(f"no source {name}; known: {known}")


def _lists(known_gaps_file: Path) -> dict[str, Any]:
    return read_toml(known_gaps_file)
