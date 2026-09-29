from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class _Result(Protocol):
    @property
    def outcome(self) -> StrEnum: ...


@dataclass(frozen=True)
class Report[R: _Result]:
    """Every result of a download or an ingest, in the order they were planned."""

    results: tuple[R, ...]

    def having(self, outcome: StrEnum) -> tuple[R, ...]:
        return tuple(each for each in self.results if each.outcome is outcome)
