from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from premium_kit import HIGH_RANK, LOW_RANK, catalog_with_dvol, legs_of, run_strategy

from sbt2.core.results import ParquetResultStore
from sbt2.core.strategy import Strategy, import_strategy, params_schema, resolve_params

PATH = "sbt2.strategies.short_premium"
STRATEGIES = [
    "ShortStrangle",
    "ShortStraddle",
    "IronCondor",
    "VerticalSpread",
    "ShortPut",
]
SHORT_PUT = "BTC-15FEB24-37500-P.DERIBIT"
SHORT_CALL = "BTC-15FEB24-57500-C.DERIBIT"


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


def sold_and_bought(
    store: ParquetResultStore, run_id: str
) -> tuple[list[str], list[str]]:
    fills = legs_of(store, run_id, "C1")
    sold = fills[fills["order_side"] == "SELL"]["instrument_id"]
    bought = fills[fills["order_side"] == "BUY"]["instrument_id"]
    return sorted(sold), sorted(bought)


@pytest.mark.integration
def test_a_short_straddle_sells_the_put_and_call_at_the_money(
    tmp_path: Path, ladder: Path
) -> None:
    store, run_id = run_strategy(tmp_path, ladder, "ShortStraddle")

    sold, bought = sold_and_bought(store, run_id)
    assert sold == ["BTC-15FEB24-45000-C.DERIBIT", "BTC-15FEB24-45000-P.DERIBIT"]
    assert bought == []


@pytest.mark.integration
def test_an_iron_condor_buys_wings_nearest_the_wing_delta(
    tmp_path: Path, ladder: Path
) -> None:
    store, run_id = run_strategy(tmp_path, ladder, "IronCondor")

    sold, bought = sold_and_bought(store, run_id)
    assert sold == [SHORT_PUT, SHORT_CALL]
    assert bought == ["BTC-15FEB24-35000-P.DERIBIT", "BTC-15FEB24-60000-C.DERIBIT"]


@pytest.mark.integration
@pytest.mark.parametrize(
    ("side", "short", "long"),
    [
        ("put", SHORT_PUT, "BTC-15FEB24-35000-P.DERIBIT"),
        ("call", SHORT_CALL, "BTC-15FEB24-60000-C.DERIBIT"),
    ],
)
def test_a_vertical_spread_sells_delta_and_buys_wing_delta_on_one_side(
    tmp_path: Path, ladder: Path, side: str, short: str, long: str
) -> None:
    store, run_id = run_strategy(tmp_path, ladder, "VerticalSpread", side=side)

    assert sold_and_bought(store, run_id) == ([short], [long])


@pytest.mark.integration
def test_a_short_put_sells_the_put_nearest_the_delta(
    tmp_path: Path, ladder: Path
) -> None:
    store, run_id = run_strategy(tmp_path, ladder, "ShortPut")

    assert sold_and_bought(store, run_id) == ([SHORT_PUT], [])


@pytest.mark.integration
@pytest.mark.parametrize("name", ["IronCondor", "VerticalSpread"])
def test_a_wing_not_beyond_the_short_leg_opens_no_combo(
    tmp_path: Path, ladder: Path, name: str
) -> None:
    store, run_id = run_strategy(tmp_path, ladder, name, wing_delta=0.30)

    assert store.load(run_id, "fills").empty


NEVER = 1000


def closing_fills(store: ParquetResultStore, run_id: str) -> pd.DataFrame:
    fills = legs_of(store, run_id, "C1")
    return pd.DataFrame(fills[fills["order_side"] == "BUY"])


@pytest.mark.integration
def test_a_combo_closes_at_the_management_dte(tmp_path: Path, ladder: Path) -> None:
    store, run_id = run_strategy(
        tmp_path, ladder, "ShortStrangle", close_dte=45, profit_target=NEVER
    )

    closing = closing_fills(store, run_id)
    assert sorted(closing["instrument_id"]) == [SHORT_PUT, SHORT_CALL]
    assert set(closing["ts_event"]) == {pd.Timestamp("2024-01-01T08:00", tz="UTC")}


@pytest.mark.integration
def test_a_combo_closes_at_the_profit_target(tmp_path: Path, falling: Path) -> None:
    held = run_strategy(
        tmp_path / "held", falling, "ShortStrangle", close_dte=0, profit_target=NEVER
    )
    store, run_id = run_strategy(
        tmp_path, falling, "ShortStrangle", close_dte=0, profit_target=20
    )

    assert closing_fills(*held).empty
    assert len(closing_fills(store, run_id)) == 2


@pytest.mark.integration
def test_a_combo_closes_at_the_stop_when_one_is_set(
    tmp_path: Path, ladder: Path
) -> None:
    held = run_strategy(
        tmp_path / "held", ladder, "ShortStrangle", close_dte=0, profit_target=NEVER
    )
    store, run_id = run_strategy(
        tmp_path,
        ladder,
        "ShortStrangle",
        close_dte=0,
        profit_target=NEVER,
        loss_target=20,
    )

    assert closing_fills(*held).empty
    assert len(closing_fills(store, run_id)) == 2


@pytest.mark.integration
def test_a_new_combo_opens_only_after_the_last_one_closed(
    tmp_path: Path, ladder: Path
) -> None:
    store, run_id = run_strategy(
        tmp_path, ladder, "ShortStrangle", close_dte=45, profit_target=NEVER
    )

    spans = [
        (fills["ts_event"].min(), fills["ts_event"].max())
        for each in ("C1", "C2", "C3")
        if not (fills := legs_of(store, run_id, each)).empty
    ]
    assert len(spans) == 3
    for (_, closed), (opened, _) in pairwise(spans):
        assert opened > closed


def legs_opened(store: ParquetResultStore, run_id: str) -> int:
    return len(legs_of(store, run_id, "C1"))


@pytest.mark.integration
def test_iv_regime_opens_an_iron_condor_below_the_threshold(tmp_path: Path) -> None:
    catalog = catalog_with_dvol(tmp_path / "catalog", LOW_RANK)

    store, run_id = run_strategy(tmp_path, catalog, "IvRegime")

    assert legs_opened(store, run_id) == 4


@pytest.mark.integration
def test_iv_regime_opens_a_strangle_at_or_above_the_threshold(tmp_path: Path) -> None:
    catalog = catalog_with_dvol(tmp_path / "catalog", HIGH_RANK)

    store, run_id = run_strategy(tmp_path, catalog, "IvRegime")

    assert legs_opened(store, run_id) == 2


@pytest.mark.integration
@pytest.mark.parametrize(
    ("dvol", "band", "opened"),
    [
        (LOW_RANK, {"min_iv_rank": 0.5}, 0),
        (HIGH_RANK, {"min_iv_rank": 0.5}, 2),
        (HIGH_RANK, {"max_iv_rank": 0.5}, 0),
        (LOW_RANK, {"max_iv_rank": 0.5}, 2),
    ],
)
def test_no_combo_opens_outside_the_iv_rank_band(
    tmp_path: Path, dvol: dict[int, float], band: dict[str, float], opened: int
) -> None:
    catalog = catalog_with_dvol(tmp_path / "catalog", dvol)

    store, run_id = run_strategy(tmp_path, catalog, "ShortStrangle", **band)

    assert legs_opened(store, run_id) == opened
