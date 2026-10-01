"""A month of real Bybit BTCUSDT; run with ``pytest -m realdata``.

The run reuses the repo's ``data/`` raw files and catalog, fetching the days
they lack, and stores its result in a throwaway folder.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model import (
    FundingRateUpdate,
    InstrumentId,
    MarkPriceUpdate,
    Money,
)
from typer.testing import CliRunner

from sbt2.cli import app
from sbt2.data import Catalog, Window
from sbt2.results import ParquetResultStore

HERE = Path(__file__).parent
REPO = HERE.parents[1]
INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")
START = datetime(2025, 1, 1, tzinfo=UTC)
END = datetime(2025, 2, 1, tzinfo=UTC)
USDT_PRECISION = 1e-8


@dataclass(frozen=True)
class MonthRun:
    runs: pd.DataFrame
    fills: pd.DataFrame
    carry: pd.DataFrame
    funding: pd.DataFrame
    marks: pd.DataFrame


@pytest.fixture(scope="module", params=["btcusdt_month", "btcusdt_month_candles"])
def month(
    tmp_path_factory: pytest.TempPathFactory, request: pytest.FixtureRequest
) -> MonthRun:
    spec = HERE / f"{request.param}.toml"
    data = _data_folder(tmp_path_factory.mktemp("data"))
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(REPO)
        result = CliRunner().invoke(app, ["run", str(spec), "--data", str(data)])
    assert result.exit_code == 0, result.output
    return _month_run(data)


def _data_folder(root: Path) -> Path:
    shared = REPO / "data"
    for folder in ("raw", "catalog"):
        (shared / folder).mkdir(parents=True, exist_ok=True)
        (root / folder).symlink_to(shared / folder, target_is_directory=True)
    return root


def _month_run(data: Path) -> MonthRun:
    store = ParquetResultStore(data / "results")
    runs = store.runs()
    [run_id] = runs["run_id"]
    catalog = Catalog(data / "catalog")
    window = Window(START, END)
    return MonthRun(
        runs=runs,
        fills=store.load(run_id, "fills").sort_values("ts_event"),
        carry=store.load(run_id, "carry"),
        funding=catalog.frame(INSTRUMENT_ID, FundingRateUpdate, window),
        marks=catalog.frame(INSTRUMENT_ID, MarkPriceUpdate, window),
    )


def signed_position(fills: pd.DataFrame, moment: pd.Timestamp) -> float:
    done = fills.loc[fills["ts_event"] <= moment]
    signs = done["order_side"].eq("BUY") * 2.0 - 1.0
    return float((signs * done["last_qty"].astype(float)).sum())


def mark_at(marks: pd.DataFrame, moment: pd.Timestamp) -> float:
    return float(marks.loc[:moment, "price"].iloc[-1])


def settlements_in_position(month: MonthRun) -> list[pd.Timestamp]:
    first_fill = month.fills["ts_event"].iloc[0]
    times = month.funding.index
    return [each for each in times if first_fill <= each < pd.Timestamp(END)]


@pytest.mark.realdata
@pytest.mark.e2e
def test_the_month_runs_and_stores_one_run(month: MonthRun) -> None:
    assert len(month.runs) == 1
    assert not month.fills.empty


@pytest.mark.realdata
@pytest.mark.e2e
def test_the_carry_ledger_has_a_payment_at_every_settlement_while_in_position(
    month: MonthRun,
) -> None:
    expected = settlements_in_position(month)

    assert list(month.carry["ts_event"]) == expected


@pytest.mark.realdata
@pytest.mark.e2e
def test_each_payment_is_the_rate_times_the_mark_notional(month: MonthRun) -> None:
    rates = month.funding["rate"]
    expected = [
        -signed_position(month.fills, ts) * mark_at(month.marks, ts) * rates[ts]
        for ts in month.carry["ts_event"]
    ]

    paid = [Money.from_str(each).as_double() for each in month.carry["pnl_change"]]

    assert paid == pytest.approx(expected, abs=USDT_PRECISION)
