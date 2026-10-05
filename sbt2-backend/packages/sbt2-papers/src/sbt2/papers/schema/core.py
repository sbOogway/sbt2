from datetime import date
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator
from pydantic import Field as PydanticField


class FieldStatus(StrEnum):
    STATED = "stated"
    INFERRED = "inferred"
    MISSING = "missing"


class Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def check_status(value: object, status: FieldStatus) -> None:
    has_value = value is not None
    if has_value == (status is FieldStatus.MISSING):
        raise ValueError(
            "a missing field has no value; a stated or inferred field has one"
        )


class Field[T](Record):
    """One piece of strategy content, with how the paper gives it."""

    value: T | None = PydanticField(
        default=None, description="The content. Null when the status is missing."
    )
    status: FieldStatus = PydanticField(
        description="stated: the paper says it. inferred: read from the paper's text. "
        "missing: the paper does not give it."
    )

    @model_validator(mode="after")
    def _value_follows_status(self) -> Self:
        check_status(self.value, self.status)
        return self


class Paper(Record):
    """The identity of a paper, as the acquire stage finds it."""

    title: str = PydanticField(description="The title of the paper.")
    authors: list[str] = PydanticField(description="The authors, in the order given.")
    first_published: date = PydanticField(
        description="The date of the first public version."
    )
    arxiv_id: str | None = PydanticField(default=None, description="The arXiv id.")
    ssrn_id: str | None = PydanticField(default=None, description="The SSRN id.")
    doi: str | None = PydanticField(default=None, description="The DOI.")

    @model_validator(mode="after")
    def _has_an_identifier(self) -> Self:
        if self.arxiv_id is None and self.ssrn_id is None and self.doi is None:
            raise ValueError("a paper needs an arXiv id, an SSRN id or a DOI")
        return self


class Period(Record):
    """A range of dates, both ends included."""

    start: date = PydanticField(description="The first date.")
    end: date = PydanticField(description="The last date. Not before the start.")

    @model_validator(mode="after")
    def _ends_after_start(self) -> Self:
        if self.end < self.start:
            raise ValueError("a period cannot end before it starts")
        return self
