from pathlib import Path

import pytest
from served_spec import DAY, NEXT_DAY, served
from typer.testing import CliRunner

from sbt2.cli import app
from sbt2.core.results import ParquetResultStore
from sbt2.data.testing import ServedSource

runner = CliRunner()
TAKER_RATE = "0.00055"


def run_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    return served(tmp_path, monkeypatch, source)


def taker_rates(tmp_path: Path) -> list[str]:
    """The taker rate in each stored run's spec, oldest run first."""
    store = ParquetResultStore(tmp_path / "data" / "results")
    return [
        store.spec(run_id)["venue"]["fee_model"]["config"]["taker_rate"]
        for run_id in store.runs()["run_id"]
    ]


@pytest.mark.e2e
def test_run_takes_its_fees_from_the_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    spec.write_text(spec.read_text().replace(TAKER_RATE, "0.0042"))

    result = runner.invoke(app, ["run", str(spec)])

    assert result.exit_code == 0, result.output
    assert taker_rates(tmp_path) == ["0.0042"]


@pytest.mark.e2e
def test_an_edited_fee_applies_to_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    spec.write_text(spec.read_text().replace(TAKER_RATE, "0.0011"))
    first = runner.invoke(app, ["run", str(spec)])
    spec.write_text(spec.read_text().replace("0.0011", "0.0022"))

    second = runner.invoke(app, ["run", str(spec)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert taker_rates(tmp_path) == ["0.0011", "0.0022"]
