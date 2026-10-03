from abc import ABC, abstractmethod
from dataclasses import Field, asdict
from datetime import datetime
from itertools import pairwise
from typing import Any, ClassVar

PARTS = ("train", "validation", "test")

type Period = tuple[datetime, datetime]


class Splitter(ABC):
    """Divides a period into train, validation and test parts.

    Subclasses are frozen dataclasses whose fields are the arguments a spec
    file's split table gives them.
    """

    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]

    def parts(self, period: Period) -> dict[str, Period]:
        start, end = period
        edges = (start, *self._boundaries(period), end)
        return dict(zip(PARTS, pairwise(edges), strict=True))

    def document(self) -> dict[str, Any]:
        """The splitter as plain data: its ``kind`` and its arguments."""
        # The kind is hashed with every run; per-class names would change them all.
        return {"kind": "Split", **asdict(self)}

    @abstractmethod
    def _boundaries(self, period: Period) -> tuple[datetime, datetime]:
        """Where validation and test start inside ``period``."""
