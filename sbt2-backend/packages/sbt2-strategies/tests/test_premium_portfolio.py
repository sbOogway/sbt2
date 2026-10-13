from collections import Counter
from decimal import Decimal
from pathlib import Path

import pytest
from option_catalog import build_staggered_catalog, write_dvol
from premium_kit import LOW_RANK, Scenario, run_scenario, run_strategy
from premium_probe import ProbePortfolio

from sbt2.core.strategy import Combo, import_strategy, params_schema, resolve_params
from sbt2.strategies.premium_sizing import kelly_fraction

PATH = "sbt2.strategies.premium_portfolio:PremiumPortfolio"
PROBE = "premium_probe:ProbePortfolio"
NEVER = 1000
TWO_DAYS = {
    "core_dte": 2,
    "supplemental_dte": 2,
    "close_dte": 0,
    "profit_target": NEVER,
}
STRANGLE, CONDOR = "short strangle", "iron condor"


@pytest.fixture(scope="module")
def staggered(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("staggered_catalog")
    build_staggered_catalog(path)
    write_dvol(path, LOW_RANK)
    return path


def expiry_of(combo: Combo) -> int:
    return min(leg.contract.expiration_ns for leg in combo.legs)


@pytest.mark.unit
def test_the_defaults_follow_the_book() -> None:
    params = resolve_params(import_strategy(PATH), {})

    assert (params.core_delta, params.core_dte, params.core_pop) == (0.16, 45, 0.79)
    assert params.supplemental_delta == 0.16
    assert (params.wing_delta, params.supplemental_dte) == (0.10, 45)
    assert params.supplemental_pop == 0.70
    assert params.ladder == 3
    assert (params.close_dte, params.profit_target) == (21, Decimal(50))
    assert params.loss_target == 0
    assert (params.risk_free, params.correlation_group) == (0.03, 0.7)
    assert params.allocation_low == Decimal("0.25")
    assert params.allocation_high == Decimal("0.50")


@pytest.mark.unit
def test_the_params_schema_lists_the_portfolio_parameters() -> None:
    names = {each.name for each in params_schema(import_strategy(PATH))}

    assert {"core_delta", "core_dte", "core_pop"} <= names
    assert {"supplemental_delta", "wing_delta", "supplemental_dte"} <= names
    assert {"supplemental_pop", "ladder", "risk_free", "correlation_group"} <= names
    assert {"close_dte", "profit_target", "loss_target"} <= names
    assert {"allocation_low", "allocation_high", "interval_hours"} <= names


@pytest.mark.integration
def test_the_core_book_opens_strangles_and_the_supplemental_book_iron_condors(
    tmp_path: Path, staggered: Path
) -> None:
    ProbePortfolio.clear()

    run_strategy(tmp_path, staggered, PROBE, ladder=2, **TWO_DAYS)

    names = Counter(combo.name for combo, _ in ProbePortfolio.opened)
    assert set(names) == {STRANGLE, CONDOR}
    condor = next(c for c, _ in ProbePortfolio.opened if c.name == CONDOR)
    assert len(condor.legs) == 4
    assert sum(leg.is_short for leg in condor.legs) == 2


@pytest.mark.integration
def test_each_book_holds_at_most_ladder_combos_on_staggered_expiries(
    tmp_path: Path, staggered: Path
) -> None:
    ProbePortfolio.clear()

    run_strategy(tmp_path, staggered, PROBE, ladder=2, **TWO_DAYS)

    for name in (STRANGLE, CONDOR):
        held = [
            [each for each in combos if each.name == name]
            for combo, combos in ProbePortfolio.opened
            if combo.name == name
        ]
        assert max(len(each) for each in held) == 2
        expiries = [expiry_of(each) for each in held[-1]]
        assert len(set(expiries)) == 2


@pytest.mark.integration
def test_combo_size_follows_the_pop_weights_of_the_allocation(
    tmp_path: Path, staggered: Path
) -> None:
    ProbePortfolio.clear()

    run_strategy(tmp_path, staggered, PROBE, ladder=2, **TWO_DAYS)

    core = kelly_fraction(0.03, 2, 0.79)
    supplemental = kelly_fraction(0.03, 2, 0.70)
    [first, *_] = [s for s in ProbePortfolio.submitted if s.combo.name == STRANGLE]
    rank = (51.0 - 30.0) / (100.0 - 30.0)
    allocation = Decimal("0.25") + Decimal("0.25") * Decimal(str(rank))
    share = Decimal(str(core / (core + supplemental)))
    target = share * allocation * first.equity / 2
    [leg, *_] = first.combo.legs
    one_step = first.bpr / leg.quantity * Decimal("0.1")
    assert first.bpr <= target
    assert target - first.bpr < one_step


@pytest.mark.integration
def test_a_combo_the_rules_refuse_is_not_retried_on_the_same_tick(
    tmp_path: Path, staggered: Path
) -> None:
    ProbePortfolio.clear()
    tight = "[risk.short_premium]\nundefined_cap = 0.0001\ndefined_cap = 0.0001\n"

    store, run_id = run_scenario(
        tmp_path, staggered, Scenario(PROBE, tight), ladder=2, **TWO_DAYS
    )

    assert store.load(run_id, "fills").empty
    tries = Counter((moment, combo.name) for moment, combo in ProbePortfolio.declined)
    assert {name for _, name in tries} == {STRANGLE, CONDOR}
    assert set(tries.values()) == {1}
