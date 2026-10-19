import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from combo_strategies import LADDER_EXPIRY, OpenStrangle
from nautilus_trader.model import black_scholes_greeks
from option_catalog import INDEX_PRICE, MARK_IV, build_ladder_catalog
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
def test_a_refused_combo_is_logged_with_its_reason(
    tmp_path: Path, ladder: Path, caplog: pytest.LogCaptureFixture
) -> None:
    OpenStrangle.clear()

    with caplog.at_level(logging.WARNING):
        run_options(
            tmp_path, ladder, Scenario("combo_strategies:OpenStrangle", SMALL_CAPS)
        )

    [(_, reason)] = OpenStrangle.declined
    [record] = [each for each in caplog.records if "refused" in each.message]
    assert record.levelno == logging.WARNING
    assert "BTC-12JAN24-40000-P.DERIBIT" in record.message
    assert "BTC-12JAN24-50000-C.DERIBIT" in record.message
    assert reason in record.message


@pytest.mark.integration
def test_an_option_run_stores_the_combos_the_rules_refuse(
    tmp_path: Path, ladder: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(
        tmp_path, ladder, Scenario("combo_strategies:OpenStrangle", SMALL_CAPS)
    )

    rows = store.load(run_id, "refusals")
    [(_, reason)] = OpenStrangle.declined
    assert list(rows.columns) == ["ts_event", "legs", "reason"]
    [row] = rows.to_dict("records")
    assert row["ts_event"] == pd.Timestamp("2024-01-01T03:00:00", tz="UTC")
    assert list(row["legs"]) == [
        "BTC-12JAN24-40000-P.DERIBIT",
        "BTC-12JAN24-50000-C.DERIBIT",
    ]
    assert row["reason"] == reason


@pytest.mark.integration
def test_the_summary_counts_the_refused_combos(tmp_path: Path, ladder: Path) -> None:
    (tmp_path / "refusing").mkdir()
    (tmp_path / "plain").mkdir()
    OpenStrangle.clear()
    store, refusing = run_options(
        tmp_path / "refusing",
        ladder,
        Scenario("combo_strategies:OpenStrangle", SMALL_CAPS),
    )
    OpenStrangle.clear()
    store_without, plain = run_options(
        tmp_path / "plain", ladder, "combo_strategies:OpenStrangle"
    )

    counts = store.runs().set_index("run_id")["refused_combos"]
    assert counts[refusing] == len(store.load(refusing, "refusals")) == 1
    assert store_without.runs().set_index("run_id")["refused_combos"][plain] == 0


@pytest.mark.integration
def test_a_run_without_the_table_opens_the_same_combo(
    tmp_path: Path, ladder: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(tmp_path, ladder, "combo_strategies:OpenStrangle")

    assert len(store.load(run_id, "fills")) == 2
    assert OpenStrangle.declined == []
    assert len(OpenStrangle.opened) == 1


def strangle_greeks(hour: datetime) -> tuple[float, float]:
    """The theta (in BTC per day) and the delta of the short strangle at ``hour``."""
    years = (LADDER_EXPIRY - hour) / timedelta(days=365)
    theta = delta = 0.0
    for strike, is_call in ((40000, False), (50000, True)):
        found = black_scholes_greeks(
            INDEX_PRICE, 0.0, 0.0, MARK_IV, is_call, float(strike), years
        )
        theta -= found.theta / INDEX_PRICE
        delta -= found.delta
    return theta, delta


@pytest.mark.integration
def test_an_option_run_stores_its_portfolio_greeks(
    tmp_path: Path, ladder: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = run_options(tmp_path, ladder, "combo_strategies:CloseStrangleAtDte")

    rows = store.load(run_id, "portfolio_greeks")
    assert list(rows.columns) == [
        "ts_event",
        "theta",
        "theta_ratio",
        "beta_weighted_delta",
    ]
    assert set(rows["ts_event"].diff().dropna()) == {pd.Timedelta(hours=1)}
    held = rows.loc[rows["beta_weighted_delta"] != 0]
    assert len(held) > 30
    [balance] = OpenStrangle.balances
    for row in held.itertuples():
        theta, delta = strangle_greeks(row.ts_event.to_pydatetime())
        assert row.theta == pytest.approx(theta)
        assert row.beta_weighted_delta == pytest.approx(delta)
        assert row.theta_ratio == pytest.approx(theta / float(balance))
    closed = rows.loc[rows["ts_event"] > datetime(2024, 1, 2, 21, tzinfo=UTC)]
    assert not closed.empty
    assert set(closed["theta"]) == set(closed["beta_weighted_delta"]) == {0.0}
