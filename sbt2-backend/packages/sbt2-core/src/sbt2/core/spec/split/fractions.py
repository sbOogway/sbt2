from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from sbt2.core.spec.errors import SpecError
from sbt2.core.spec.moments import nearest_day
from sbt2.core.spec.split.splitter import PARTS, Period, Splitter


class SplitFractionError(SpecError):
    pass


@dataclass(frozen=True)
class FractionSplit(Splitter):
    """Validation and test as the fractions of the period that end it.

    Boundaries are rounded to the nearest whole UTC day; the period's own ends
    are kept.
    """

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

    def _boundaries(self, period: Period) -> tuple[datetime, datetime]:
        start, end = period
        length = end - start
        boundaries = (
            nearest_day(end - length * (self.validation + self.test)),
            nearest_day(end - length * self.test),
        )
        _check_parts_have_length((start, *boundaries, end))
        return boundaries


def _check_parts_have_length(edges: tuple[datetime, ...]) -> None:
    for part, (start, end) in zip(PARTS, pairwise(edges), strict=True):
        if start >= end:
            raise SplitFractionError(
                f"the {part} part is empty once its boundaries are rounded "
                "to whole days"
            )
