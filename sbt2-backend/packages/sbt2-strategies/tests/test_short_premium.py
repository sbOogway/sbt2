from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from premium_kit import run_strategy

from sbt2.core.strategy import Strategy, import_strategy, params_schema, resolve_params

PATH = "sbt2.strategies.short_premium"
STRATEGIES = ["ShortStrangle"]
SHORT_PUT = "BTC-15FEB24-35000-P.DERIBIT"
SHORT_CALL = "BTC-15FEB24-55000-C.DERIBIT"


def strategy(name: str) -> type[Strategy[Any]]:
    return import_strategy(f"{PATH}:{name}")


@pytest.mark.unit
def test_the_defaults_follow_the_book() -> None:
    params = resolve_params(strategy("ShortStrangle"), {})

    assert params.delta == 0.16
    assert params.dte == 45
    assert params.close_dte == 21
    assert params.profit_target == Decimal(50)
    assert params.loss_target == 0


@pytest.mark.unit
@pytest.mark.parametrize("name", STRATEGIES)
def test_the_params_schema_lists_the_book_parameters(name: str) -> None:
    names = [each.name for each in params_schema(strategy(name))]

    assert {"dte", "close_dte", "profit_target", "loss_target"} <= set(names)
    assert {"min_iv_rank", "max_iv_rank", "quantity", "interval_hours"} <= set(names)


@pytest.mark.integration
def test_a_short_strangle_sells_the_put_and_call_nearest_the_delta(
    tmp_path: Path, ladder: Path
) -> None:
    store, run_id = run_strategy(tmp_path, ladder, "ShortStrangle")

    fills = store.load(run_id, "fills")
    assert sorted(fills["instrument_id"]) == [SHORT_PUT, SHORT_CALL]
    assert set(fills["order_side"]) == {"SELL"}
