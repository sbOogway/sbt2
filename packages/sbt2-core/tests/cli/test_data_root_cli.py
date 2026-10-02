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


DAYS = ["--start", "2025-01-01", "--end", "2025-01-01"]
SOURCED = ["--source", "bybit", "--symbol", "BTCUSDT", *DAYS]


def tree(folder: Path) -> list[Path]:
    return sorted(folder.rglob("*"))


@pytest.mark.e2e
@pytest.mark.parametrize(
    "command",
    [
        ["run", "spec.toml"],
        ["download", *SOURCED],
        ["ingest", *SOURCED],
        ["data", "status"],
        ["runs", "list"],
        ["runs", "show", "a-run"],
        ["runs", "delete", "a-run", "--yes"],
        ["report", "tearsheet", "a-run"],
        ["report", "parts", "a-run"],
        ["report", "batch", "a-batch"],
    ],
    ids=" ".join,
)
def test_every_data_command_fails_without_a_data_root(
    command: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SBT2_DATA", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    before = tree(tmp_path)

    result = runner.invoke(app, command)

    assert result.exit_code == 2, result.output
    assert "--data" in result.output
    assert "SBT2_DATA" in result.output
    assert tree(tmp_path) == before
