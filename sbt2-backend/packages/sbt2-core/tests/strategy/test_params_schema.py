from dataclasses import dataclass
from typing import Literal

import pytest
from toy_strategies import BuyEveryBar

from sbt2.core.strategy import InvalidParameterError, resolve_params


@dataclass(frozen=True)
class ModeParams:
    mode: Literal["fast", "slow"] = "fast"


class ModeStrategy(BuyEveryBar):
    Params = ModeParams


@pytest.mark.unit
def test_a_value_outside_a_literal_is_rejected() -> None:
    assert resolve_params(ModeStrategy, {"mode": "slow"}) == ModeParams("slow")
    with pytest.raises(InvalidParameterError, match="mode must be one of"):
        resolve_params(ModeStrategy, {"mode": "medium"})
