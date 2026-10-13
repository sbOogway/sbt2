"""A month of real Deribit BTC options; run with ``pytest -m realdata``.

The run reuses the repo's ``data/`` raw files and catalog, fetching the days
they lack, and stores its result in a throwaway folder.
"""

from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from sbt2.cli import app
from sbt2.core.results import ParquetResultStore

HERE = Path(__file__).parent
REPO = HERE.parents[3]
CONFIG = HERE.parents[2] / "sbt2-core" / "tests" / "config"
COIN_PRECISION = 1e-6


def _data_folder(root: Path) -> Path:
    shared = REPO / "data"
    for folder in ("raw", "catalog"):
        (shared / folder).mkdir(parents=True, exist_ok=True)
        (root / folder).symlink_to(shared / folder, target_is_directory=True)
    return root


def equity_after_last_trade(equity: pd.DataFrame, trades: pd.DataFrame) -> float:
    """The equity at the first sample after the last close. The strategy opens
    its next combo on a later daily tick, so none carries unrealised profit
    yet, and the sample comes before the fills of that tick."""
    after = [
        float(total)
        for moment, total in zip(
            equity["ts_event"], equity["total_equity"], strict=True
        )
        if moment > trades["ts_closed"].max()
    ]
    return after[0]


@pytest.mark.realdata
@pytest.mark.e2e
def test_a_short_strangle_runs_on_a_month_of_deribit_btc_options(
    tmp_path: Path,
) -> None:
    data = _data_folder(tmp_path)
    with pytest.MonkeyPatch.context() as patch:
        patch.chdir(REPO)
        result = CliRunner().invoke(
            app,
            [
                "run",
                str(HERE / "short_strangle_month.toml"),
                "--data",
                str(data),
                "--config",
                str(CONFIG),
            ],
        )
    assert result.exit_code == 0, result.output

    store = ParquetResultStore(data / "results")
    [run_id] = store.runs()["run_id"]
    trades = store.load(run_id, "trades")
    assert len(trades) >= 1
    equity = store.load(run_id, "equity")
    gained = equity_after_last_trade(equity, trades) - 1.0
    assert trades["pl"].sum() == pytest.approx(gained, abs=COIN_PRECISION)
