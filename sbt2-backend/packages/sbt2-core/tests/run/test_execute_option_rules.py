from pathlib import Path

import pytest
from combo_strategies import OpenStrangle
from option_catalog import build_ladder_catalog
from option_runs import Scenario, run_options

SMALL_CAPS = """
[risk.short_premium]
undefined_cap = 0.001
defined_cap = 0.001
"""


@pytest.fixture(scope="module")
def ladder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("ladder_catalog")
    build_ladder_catalog(path)
    return path


@pytest.mark.integration
def test_a_refused_combo_sends_no_leg_and_calls_on_combo_refused(
    tmp_path: Path, ladder: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(
        tmp_path, ladder, Scenario("combo_strategies:OpenStrangle", SMALL_CAPS)
    )

    assert store.load(run_id, "fills").empty
    assert OpenStrangle.opened == []
    [(combo, reason)] = OpenStrangle.declined
    assert combo.name == "short strangle"
    assert reason.startswith("undefined_cap")
    assert "BPR" in reason


@pytest.mark.integration
def test_a_run_without_the_table_opens_the_same_combo(
    tmp_path: Path, ladder: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(tmp_path, ladder, "combo_strategies:OpenStrangle")

    assert len(store.load(run_id, "fills")) == 2
    assert OpenStrangle.declined == []
    assert len(OpenStrangle.opened) == 1
