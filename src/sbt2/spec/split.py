from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timedelta
from itertools import pairwise
from typing import Any, Protocol

from sbt2.spec.parse import utc

PARTS = ("train", "validation", "test")
_DAY = timedelta(days=1)

type Period = tuple[datetime, datetime]
type Moment = date | datetime | str


class UnknownSplitError(ValueError):
    """A split table whose keys fit no splitter."""


class SplitFractionError(ValueError):
    pass


class SplitFormError(ValueError):
    """A split given neither all its fractions nor all its dates."""


class SplitDateError(ValueError):
    pass


class Splitter(Protocol):
    """Divides a period into train, validation and test parts."""

    def parts(self, period: Period) -> dict[str, Period]: ...

    def document(self) -> dict[str, Any]:
        """The splitter as plain data: its ``kind`` and its arguments."""
        ...


@dataclass(frozen=True)
class _Fractions:
    validation: float
    test: float

    def __post_init__(self) -> None:
        if self.validation <= 0 or self.test <= 0:
            raise SplitFractionError(
                f"fractions must be positive, got validation={self.validation} "
                f"and test={self.test}"
            )
        if self.validation + self.test >= 1:
            raise SplitFractionError(
                f"validation={self.validation} and test={self.test} must add up "
                "to less than 1, leaving a train part"
            )

    def boundaries(self, period: Period) -> tuple[datetime, datetime]:
        start, end = period
        length = end - start
        boundaries = (
            _nearest_day(end - length * (self.validation + self.test)),
            _nearest_day(end - length * self.test),
        )
        _check_parts_have_length((start, *boundaries, end))
        return boundaries


@dataclass(frozen=True)
class _Dates:
    validation_start: datetime
    test_start: datetime

    def __post_init__(self) -> None:
        if self.validation_start >= self.test_start:
            raise SplitDateError(
                f"validation_start {self.validation_start} must be before "
                f"test_start {self.test_start}"
            )

    def boundaries(self, period: Period) -> tuple[datetime, datetime]:
        start, end = period
        if not start < self.validation_start or not self.test_start < end:
            raise SplitDateError(
                f"validation_start {self.validation_start} and test_start "
                f"{self.test_start} must be inside the period {start} to {end}"
            )
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
    _form: _Fractions | _Dates = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        form = self._chosen_form()
        object.__setattr__(self, "_form", form)
        if isinstance(form, _Dates):
            object.__setattr__(self, "validation_start", form.validation_start)
            object.__setattr__(self, "test_start", form.test_start)

    @classmethod
    def from_table(cls, table: Mapping[str, Any]) -> Split:
        """The split a spec file's table of arguments describes."""
        unknown = sorted(set(table) - {each.name for each in fields(cls) if each.init})
        if unknown:
            raise UnknownSplitError(
                f"split keys {', '.join(unknown)} fit no split; a split takes "
                "validation and test, or validation_start and test_start"
            )
        return cls(**table)

    def parts(self, period: Period) -> dict[str, Period]:
        start, end = period
        edges = (start, *self._form.boundaries(period), end)
        return dict(zip(PARTS, pairwise(edges), strict=True))

    def document(self) -> dict[str, Any]:
        return {"kind": "Split", **asdict(self._form)}

    def _chosen_form(self) -> _Fractions | _Dates:
        validation, test = self.validation, self.test
        validation_start, test_start = self.validation_start, self.test_start
        if (
            validation is not None
            and test is not None
            and validation_start is None
            and test_start is None
        ):
            return _Fractions(validation, test)
        if (
            validation_start is not None
            and test_start is not None
            and validation is None
            and test is None
        ):
            return _Dates(_day(validation_start), _day(test_start))
        raise SplitFormError(
            "a split takes the validation and test fractions, or the "
            f"validation_start and test_start dates; got {self}"
        )


def _check_parts_have_length(edges: tuple[datetime, ...]) -> None:
    for part, (start, end) in zip(PARTS, pairwise(edges), strict=True):
        if start >= end:
            raise SplitFractionError(
                f"the {part} part is empty once its boundaries are rounded "
                "to whole days"
            )


def _day(moment: Moment) -> datetime:
    return _midnight(utc(moment))


def _nearest_day(moment: datetime) -> datetime:
    midnight = _midnight(moment)
    return midnight + _DAY if moment - midnight >= _DAY / 2 else midnight


def _midnight(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)
