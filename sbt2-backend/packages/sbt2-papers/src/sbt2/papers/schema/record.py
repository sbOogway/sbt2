from typing import Literal

from pydantic import Field as PydanticField

from sbt2.papers.schema.core import Paper, Record
from sbt2.papers.schema.trading import TradingStrategy


class PaperRecord(Record):
    """What the extraction of one paper produces."""

    schema_version: Literal[1] = PydanticField(
        description="The version of this schema. Always 1."
    )
    paper: Paper = PydanticField(description="The paper.")
    strategies: list[TradingStrategy] = PydanticField(
        description="The tradable rules of the paper. Empty when it has none."
    )
