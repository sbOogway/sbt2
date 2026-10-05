"""Sources of uploaded strategy modules."""

import textwrap

HEADER = """\
import os
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from nautilus_trader.model import BarSpecification

from sbt2.core.strategy import Strategy
"""
STRATEGY = (
    HEADER
    + '''

@dataclass(frozen=True)
class Params:
    """The averages."""

    slow: int
    fast: int = 10
    step: Decimal = Decimal("0.100")
    mode: Literal["ema", "sma"] = "ema"


class Cross(Strategy[Params]):
    """Buys on a cross."""

    Params = Params

    @classmethod
    def inputs(cls, params: Params) -> Sequence[BarSpecification]:
        return ()
'''
)


def with_params(fields: str, name: str = "Cross") -> str:
    return (
        HEADER
        + f"""

@dataclass(frozen=True)
class Params:
{textwrap.indent(fields, "    ")}


class {name}(Strategy[Params]):
    Params = Params

    @classmethod
    def inputs(cls, params: Params) -> Sequence[BarSpecification]:
        return ()
"""
    )
