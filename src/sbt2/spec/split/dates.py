from dataclasses import dataclass
from datetime import datetime

from sbt2.spec.errors import SpecError
from sbt2.spec.moments import Moment, floor_day, utc
from sbt2.spec.split.splitter import Period, Splitter


class SplitDateError(SpecError):
    pass


@dataclass(frozen=True, init=False)
class DateSplit(Splitter):
    """Validation and test by the dates they start on, floored to their UTC day."""

    validation_start: datetime
    test_start: datetime

    def __init__(self, validation_start: Moment, test_start: Moment) -> None:
        object.__setattr__(self, "validation_start", _day(validation_start))
        object.__setattr__(self, "test_start", _day(test_start))
        if self.validation_start >= self.test_start:
            raise SplitDateError(
                f"validation_start {self.validation_start} must be before "
                f"test_start {self.test_start}"
            )

    def _boundaries(self, period: Period) -> tuple[datetime, datetime]:
        start, end = period
        if not start < self.validation_start or not self.test_start < end:
            raise SplitDateError(
                f"validation_start {self.validation_start} and test_start "
                f"{self.test_start} must be inside the period {start} to {end}"
            )
        return self.validation_start, self.test_start


def _day(moment: Moment) -> datetime:
    return floor_day(utc(moment))
