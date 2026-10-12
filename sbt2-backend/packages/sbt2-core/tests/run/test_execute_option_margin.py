from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
from option_catalog import (
    EXPIRING_CALL,
    EXPIRY_HOUR,
    HOURS,
    OPTION_ID,
    START,
    build_expiring_catalog,
    build_option_catalog,
    mark_at,
)
from run_strategies import ReadOrderMargin, ReadPositionMargin, SellTenOptions

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "run_strategies:SellOneOption"
instruments = ["BTC-1FEB24-50000-C.DERIBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
venue = "deribit_option"
capital = "1 BTC"
"""
VENUES = """
[deribit_option]
name = "DERIBIT"
source = "deribit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "OPTION"
fee_model = { kind = "capped_option", config = { maker_rate = "0.0003", taker_rate = "0.0003", cap_rate = "0.125" } }
"""
HOUR_NS = 3_600 * 10**9
START_NS = int(START.timestamp()) * 10**9
FLOOR = Decimal("0.1")
MAINTENANCE = Decimal("0.075")
LOW_DELIVERY = 40_000.0


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("option_catalog")
    build_option_catalog(path)
    return path


@pytest.fixture(scope="module")
def expiring(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("expiring")
    build_expiring_catalog(path, LOW_DELIVERY)
    return path


def run(
    tmp_path: Path, catalog: Path, strategy: str, instrument: str = str(OPTION_ID)
) -> tuple[ParquetResultStore, str]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(
        SPEC.replace("run_strategies:SellOneOption", strategy).replace(
            "BTC-1FEB24-50000-C.DERIBIT", instrument
        )
    )
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog))
    return store, sink.run_id


def short_call_margin(ts: int) -> Decimal:
    """The floor plus the last mark at or before ``ts``: the call is far out of
    the money, so the floor is the larger term. The catalog's last mark is at
    its last hour."""
    hour = min((ts - START_NS) // HOUR_NS, HOURS - 1)
    return FLOOR + mark_at(hour)


@pytest.mark.integration
def test_a_strategy_reads_the_margin_of_an_order_before_it_sends_it(
    tmp_path: Path, catalog: Path
) -> None:
    ReadOrderMargin.asked.clear()

    run(tmp_path, catalog, "run_strategies:ReadOrderMargin")

    [(ts, margin)] = ReadOrderMargin.asked
    assert margin == short_call_margin(ts)


@pytest.mark.integration
def test_a_strategy_reads_the_margin_of_its_open_position(
    tmp_path: Path, catalog: Path
) -> None:
    ReadPositionMargin.read.clear()

    run(tmp_path, catalog, "run_strategies:ReadPositionMargin")

    assert len(ReadPositionMargin.read) > 1
    for ts, margins in ReadPositionMargin.read:
        assert margins == {str(OPTION_ID): short_call_margin(ts)}


@pytest.mark.integration
def test_a_short_option_order_beyond_the_free_equity_is_refused(
    tmp_path: Path, catalog: Path
) -> None:
    SellTenOptions.refused.clear()

    store, run_id = run(tmp_path, catalog, "run_strategies:SellTenOptions")

    [(instrument, reason)] = SellTenOptions.refused
    assert instrument == str(OPTION_ID)
    assert "initial margin of 1.52" in reason
    assert "free equity 1" in reason
    assert store.load(run_id, "fills").empty


def last_mark_hour(ts: int, last: int) -> int:
    return min((ts - START_NS) // HOUR_NS, last)


@pytest.mark.integration
def test_a_run_records_the_margin_used_over_time(
    tmp_path: Path, expiring: Path
) -> None:
    store, run_id = run(
        tmp_path, expiring, "run_strategies:SellOneOption", str(EXPIRING_CALL)
    )

    [fill, _] = store.load(run_id, "fills").to_dict("records")
    margin = store.load(run_id, "margin")
    equity = store.load(run_id, "equity")
    assert list(margin["ts_event"]) == list(equity["ts_event"])
    for row in margin.to_dict("records"):
        ts = pd.Timestamp(row["ts_event"])
        open_now = (
            pd.Timestamp(fill["ts_event"])
            < ts
            < pd.Timestamp(START) + pd.Timedelta(hours=EXPIRY_HOUR)
        )
        hour = last_mark_hour(ts.value, EXPIRY_HOUR - 1)
        expected = FLOOR + mark_at(hour) if open_now else Decimal(0)
        assert row["margin_used"] == pytest.approx(float(expected))
        assert row["currency"] == "BTC"
    assert margin["margin_used"].iloc[-1] == 0
    assert (margin["margin_used"] > 0).any()


@pytest.mark.integration
def test_a_run_records_the_maintenance_margin_beside_the_margin_used(
    tmp_path: Path, expiring: Path
) -> None:
    store, run_id = run(
        tmp_path, expiring, "run_strategies:SellOneOption", str(EXPIRING_CALL)
    )

    rows = store.load(run_id, "margin").to_dict("records")
    open_rows = [row for row in rows if row["margin_used"] > 0]
    assert len(open_rows) > 1
    for row in open_rows:
        hour = last_mark_hour(pd.Timestamp(row["ts_event"]).value, EXPIRY_HOUR - 1)
        assert row["maintenance_margin"] == pytest.approx(
            float(MAINTENANCE + mark_at(hour))
        )
