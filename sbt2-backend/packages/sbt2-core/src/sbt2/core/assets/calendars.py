from abc import ABC, abstractmethod
from datetime import UTC, date, datetime, timedelta
from typing import override

_RESOLUTION = timedelta(microseconds=1)


class Calendar(ABC):
    @abstractmethod
    def trading_days(self, start: datetime, end: datetime) -> list[date]:
        """UTC days with trading in the half-open window [start, end)."""
        ...


class AlwaysOpen(Calendar):
    @override
    def trading_days(self, start: datetime, end: datetime) -> list[date]:
        start, end = _utc(start), _utc(end)
        if end <= start:
            return []
        first = start.date()
        last = (end - _RESOLUTION).date()
        return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def _utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValueError(f"naive datetime {moment} has no time zone")
    return moment.astimezone(UTC)
