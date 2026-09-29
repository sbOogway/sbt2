from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Protocol

from sbt2.spec.parse import utc

PARTS = ("train", "validation", "test")
_DAY = timedelta(days=1)

type Period = tuple[datetime, datetime]
type Moment = date | datetime | str


class Splitter(Protocol):
    """Divides a period into train, validation and test parts."""

    def parts(self, period: Period) -> dict[str, Period]: ...


class _Boundaries(Protocol):
    def boundaries(self, period: Period) -> tuple[datetime, datetime]: ...


@dataclass(frozen=True)
class _Fractions:
    validation: float
    test: float

    def boundaries(self, period: Period) -> tuple[datetime, datetime]:
        start, end = period
        length = end - start
        return (
            _nearest_day(end - length * (self.validation + self.test)),
            _nearest_day(end - length * self.test),
        )


@dataclass(frozen=True)
class _Dates:
    validation_start: datetime
    test_start: datetime

    def boundaries(self, period: Period) -> tuple[datetime, datetime]:
        return self.validation_start, self.test_start


@dataclass(frozen=True)
class Split:
    """Validation and test by the fractions of the period that end it, or by
    the dates they start on.

    Fraction boundaries are rounded to the nearest whole UTC day and dates are
    floored to theirs; the period's own ends are kept.
    """

    validation: float | None = None
    test: float | None = None
    validation_start: Moment | None = None
    test_start: Moment | None = None
    _form: _Boundaries = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.validation_start is not None and self.test_start is not None:
            dates = _Dates(_day(self.validation_start), _day(self.test_start))
            object.__setattr__(self, "validation_start", dates.validation_start)
            object.__setattr__(self, "test_start", dates.test_start)
            object.__setattr__(self, "_form", dates)
        elif self.validation is not None and self.test is not None:
            object.__setattr__(self, "_form", _Fractions(self.validation, self.test))

    def parts(self, period: Period) -> dict[str, Period]:
        start, end = period
        edges = (start, *self._form.boundaries(period), end)
        return dict(zip(PARTS, pairwise(edges), strict=True))


def _day(moment: Moment) -> datetime:
    return _midnight(utc(moment))


def _nearest_day(moment: datetime) -> datetime:
    midnight = _midnight(moment)
    return midnight + _DAY if moment - midnight >= _DAY / 2 else midnight


def _midnight(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)
