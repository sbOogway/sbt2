from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import product

from sbt2.data.sources import Source


def days(start: date, end: date) -> Iterator[date]:
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


@dataclass(frozen=True)
class DayRange:
    """Symbols over an inclusive range of UTC days.

    ``data`` names the data types by their nautilus type name; empty means
    every type the source serves.
    """

    symbols: tuple[str, ...]
    start: date
    end: date
    data: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError(f"the range ends on {self.end}, before {self.start}")

    def plan(self, source: Source) -> Iterator[tuple[str, type, date]]:
        """Each symbol, data type and day ``source`` should have, skipping its known gaps."""
        types = source.served(self.data)
        span = days(self.start, self.end)
        for symbol, data_type, day in product(self.symbols, types, span):
            if not source.is_known_gap(symbol, data_type, day):
                yield symbol, data_type, day
