from collections.abc import Iterator
from datetime import date, timedelta


def days(start: date, end: date) -> Iterator[date]:
    for offset in range((end - start).days + 1):
        yield start + timedelta(days=offset)
