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
