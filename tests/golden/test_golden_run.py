import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from golden_catalog import build_catalog
from typer.testing import CliRunner

from sbt2.cli import app
from sbt2.results import ParquetResultStore

pytestmark = pytest.mark.golden

HERE = Path(__file__).parent
REPO = HERE.parents[1]
METRICS = [
    "net_return",
    "annualized_return",
    "sharpe",
    "max_drawdown",
    "trade_count",
    "total_fees",
    "total_carry",
]


def golden_numbers(store: ParquetResultStore) -> dict[str, Any]:
    [summary] = store.runs().to_dict("records")
    run_id = summary["run_id"]
    equity = store.load(run_id, "equity")
    carry = store.load(run_id, "carry")
    fills = store.load(run_id, "fills")
    return {
        "summary": {name: summary[name] for name in METRICS},
        "carry": [
            [ts.isoformat(), pnl]
            for ts, pnl in zip(carry["ts_event"], carry["pnl_change"], strict=True)
        ],
        "fills": _rows(fills, ["order_side", "last_qty", "last_px", "commission"]),
        "equity": dict(
            zip(
                [ts.isoformat() for ts in equity["ts_event"]],
                equity["total_equity"],
                strict=True,
            )
        ),
    }


def _rows(frame: pd.DataFrame, columns: list[str]) -> list[list[str]]:
    return [
        [ts.isoformat(), *map(str, values)]
        for ts, *values in frame[["ts_event", *columns]].itertuples(index=False)
    ]


@pytest.fixture
def data(tmp_path: Path) -> Path:
    build_catalog(tmp_path / "catalog")
    return tmp_path


@pytest.mark.parametrize("name", ["ma_cross"])
def test_the_spec_keeps_producing_its_golden_numbers(
    name: str,
    data: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    monkeypatch.chdir(REPO)
    spec, golden = HERE / f"{name}.toml", HERE / f"{name}.json"

    result = CliRunner().invoke(app, ["run", str(spec), "--data", str(data)])

    assert result.exit_code == 0, result.output
    numbers = golden_numbers(ParquetResultStore(data / "results"))
    if request.config.getoption("update_golden"):
        golden.write_text(json.dumps(numbers, indent=2) + "\n")
    expected = json.loads(golden.read_text())
    assert numbers["carry"], "a golden run must settle at least one funding payment"
    assert numbers["carry"] == expected["carry"]
    assert numbers["fills"] == expected["fills"]
    assert numbers["summary"] == pytest.approx(expected["summary"], rel=1e-9)
    assert numbers["equity"] == pytest.approx(expected["equity"], rel=1e-9)
