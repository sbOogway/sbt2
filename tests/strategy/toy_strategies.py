from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from sbt2.strategy import (
    Bars,
    Fill,
    Input,
    Intent,
    NoParams,
    State,
    Strategy,
    TargetPosition,
)

MINUTE_BARS = Bars("1-MINUTE-LAST")


@dataclass(frozen=True)
class StepParams:
    step: Decimal = Decimal("0.100")
    lookback: int = 3


class StepUp(Strategy[StepParams]):
    """Adds ``step`` to the real position on every bar."""

    Params = StepParams

    @classmethod
    def warmup(cls, params: StepParams) -> timedelta:
        return timedelta(minutes=params.lookback)

    @classmethod
    def inputs(cls, params: StepParams) -> Sequence[Input]:
        return (MINUTE_BARS,)

    def decide(self, state: State) -> Sequence[Intent]:
        return [
            TargetPosition(instrument_id, position + self.params.step)
            for instrument_id, position in state.positions.items()
        ]


class OneEquityUnitUntilFilled(Strategy[NoParams]):
    """Holds one unit per 10,000 of equity, and goes flat after its first fill."""

    def __init__(self, params: NoParams) -> None:
        super().__init__(params)
        self.filled = False

    @classmethod
    def inputs(cls, params: NoParams) -> Sequence[Input]:
        return (MINUTE_BARS,)

    def decide(self, state: State) -> Sequence[Intent]:
        units = Decimal(0) if self.filled else state.equity.as_decimal() / 10_000
        return [
            TargetPosition(bar_type.instrument_id, units) for bar_type in state.bars
        ]

    def on_fill(self, fill: Fill) -> None:
        self.filled = True


class NotAStrategy:
    pass
