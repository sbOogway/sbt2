from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Protocol

PARTS = ("train", "validation", "test")
_DAY = timedelta(days=1)

type Period = tuple[datetime, datetime]


class Splitter(Protocol):
    """Divides a period into train, validation and test parts."""

    def parts(self, period: Period) -> dict[str, Period]: ...


@dataclass(frozen=True)
class Split:
    """Validation and test as the fractions of the period that end it.

    Boundaries are rounded to the nearest whole UTC day; the period's own ends
    are kept.
    """

    validation: float
    test: float

    def parts(self, period: Period) -> dict[str, Period]:
        start, end = period
        edges = (start, *self._boundaries(period), end)
        return dict(zip(PARTS, pairwise(edges), strict=True))

    def _boundaries(self, period: Period) -> tuple[datetime, datetime]:
        start, end = period
        length = end - start
        return (
            _nearest_day(end - length * (self.validation + self.test)),
            _nearest_day(end - length * self.test),
        )


def _nearest_day(moment: datetime) -> datetime:
    midnight = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight + _DAY if moment - midnight >= _DAY / 2 else midnight
