from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import override

from nautilus_trader.model import BarSpecification

from sbt2.core.strategy import Strategy


@dataclass(frozen=True)
class LookbackParams:
    lookback: int = 20
    stop: Decimal = Decimal("0.02")


class MinuteLookback(Strategy[LookbackParams]):
    Params = LookbackParams

    @classmethod
    def warmup(cls, params: LookbackParams) -> timedelta:
        return timedelta(minutes=params.lookback)

    @classmethod
    @override
    def inputs(cls, params: LookbackParams) -> Sequence[BarSpecification]:
        return (BarSpecification.from_str("1-MINUTE-LAST"),)


@dataclass(frozen=True)
class BarParams:
    bar: str = "1-HOUR-LAST"


class DeclaredBar(Strategy[BarParams]):
    Params = BarParams

    @classmethod
    def inputs(cls, params: BarParams) -> Sequence[BarSpecification]:
        return (BarSpecification.from_str(params.bar),)
