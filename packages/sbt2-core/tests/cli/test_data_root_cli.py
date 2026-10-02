from pathlib import Path

import pytest
from served_source import ServedSource
from served_spec import DAY, NEXT_DAY, served
from typer.testing import CliRunner

from sbt2.core.cli import app
from sbt2.core.results import ParquetResultStore

runner = CliRunner()


def run_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    return served(tmp_path, monkeypatch, source)


def run_ids(root: Path) -> list[str]:
    return list(ParquetResultStore(root / "results").runs()["run_id"])


@pytest.mark.e2e
def test_the_data_root_comes_from_sbt2_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    root = tmp_path / "root"
    monkeypatch.setenv("SBT2_DATA", str(root))

    result = runner.invoke(app, ["run", str(spec)])

    assert result.exit_code == 0, result.output
    assert len(run_ids(root)) == 1


@pytest.mark.e2e
def test_the_data_option_wins_over_sbt2_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    a, b = tmp_path / "a", tmp_path / "b"
    monkeypatch.setenv("SBT2_DATA", str(a))

    result = runner.invoke(app, ["run", str(spec), "--data", str(b)])

    assert result.exit_code == 0, result.output
    assert len(run_ids(b)) == 1
    assert not a.exists()
