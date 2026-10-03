import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from golden_catalog import build_catalog
from typer.testing import CliRunner, Result

from sbt2.core.cli import app
from sbt2.core.results import ParquetResultStore

HERE = Path(__file__).parent
CONFIG = HERE.parent / "config"
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
        **_drawdown_trip(summary["drawdown_tripped_at"]),
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


def _drawdown_trip(tripped_at: Any) -> dict[str, str]:
    """Only a run that trips records it, so the ma_cross goldens stay as they are."""
    if not isinstance(tripped_at, pd.Timestamp):
        return {}
    return {"drawdown_tripped_at": tripped_at.isoformat()}


def _rows(frame: pd.DataFrame, columns: list[str]) -> list[list[str]]:
    return [
        [ts.isoformat(), *map(str, values)]
        for ts, *values in frame[["ts_event", *columns]].itertuples(index=False)
    ]


def run(spec: Path, data: Path) -> Result:
    return CliRunner().invoke(
        app, ["run", str(spec), "--data", str(data), "--config", str(CONFIG)]
    )


@pytest.fixture
def data(tmp_path: Path) -> Path:
    build_catalog(tmp_path / "catalog")
    return tmp_path


@pytest.mark.golden
@pytest.mark.e2e
@pytest.mark.parametrize(
    "name", ["ma_cross", "ma_cross_candles", "bracket_risk", "bracket_risk_candles"]
)
def test_the_spec_keeps_producing_its_golden_numbers(
    name: str,
    data: Path,
    request: pytest.FixtureRequest,
) -> None:
    spec, golden = HERE / f"{name}.toml", HERE / f"{name}.json"

    result = run(spec, data)

    assert result.exit_code == 0, result.output
    numbers = golden_numbers(ParquetResultStore(data / "results"))
    if request.config.getoption("update_golden"):
        golden.write_text(json.dumps(numbers, indent=2) + "\n")
    expected = json.loads(golden.read_text())
    assert numbers["carry"], "a golden run must settle at least one funding payment"
    assert numbers.get("drawdown_tripped_at") == expected.get("drawdown_tripped_at")
    assert numbers["carry"] == expected["carry"]
    assert numbers["fills"] == expected["fills"]
    assert numbers["summary"] == pytest.approx(expected["summary"], rel=1e-9)
    assert numbers["equity"] == pytest.approx(expected["equity"], rel=1e-9)


@pytest.mark.golden
@pytest.mark.e2e
@pytest.mark.parametrize("name", ["bracket_risk", "bracket_risk_candles"])
def test_the_bracket_golden_run_exercises_brackets_and_the_guard(
    name: str, data: Path
) -> None:
    result = run(HERE / f"{name}.toml", data)

    assert result.exit_code == 0, result.output
    store = ParquetResultStore(data / "results")
    [summary] = store.runs().to_dict("records")
    fills = store.load(summary["run_id"], "fills")
    assert set(fills["instrument_id"]) == {
        "BTCUSDT-LINEAR.BYBIT",
        "ETHUSDT-LINEAR.BYBIT",
    }
    assert {"LIMIT", "STOP_MARKET"} <= set(fills["order_type"])
    assert isinstance(summary["drawdown_tripped_at"], pd.Timestamp)
