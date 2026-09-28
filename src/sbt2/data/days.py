from collections.abc import Iterator
from datetime import date, timedelta

from sbt2.sources import Gap, Source, UnsupportedDataTypeError


def data_types(source: Source, names: tuple[str, ...]) -> tuple[type, ...]:
    """The source's data types called ``names``; all of them when ``names`` is empty."""
    served = {each.__name__: each for each in source.data_types}
    unknown = [each for each in names if each not in served]
    if unknown:
        raise UnsupportedDataTypeError(
            f"the source serves no {', '.join(unknown)}; it serves {', '.join(served)}"
        )
    return tuple(served[each] for each in names) or source.data_types


def days(start: date, end: date) -> Iterator[date]:
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)


def is_known_gap(source: Source, symbol: str, data_type: type, day: date) -> bool:
    return Gap(source.instrument_id(symbol), data_type, day) in source.known_gaps
