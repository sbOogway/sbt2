from pathlib import Path

import pytest
from served_source import ServedSource
from served_spec import DAY, NEXT_DAY, VALIDATION_DAY, served, without_a_part
from typer.testing import CliRunner

from sbt2.core.cli import app
from sbt2.core.results import ParquetResultStore, StoredStudy

runner = CliRunner()
MA_CROSS = "crossover:MovingAverageCross"


def in_study(spec: Path, name: str, fast: str) -> Path:
    """The served spec in study ``name``, its ``fast`` parameter set to ``fast``."""
    text = spec.read_text().replace("fast = 1", f"fast = {fast}")
    spec.write_text(f'study = "{name}"\n{text}')
    return spec


def run(spec: Path) -> None:
    result = runner.invoke(app, ["run", str(spec)])
    assert result.exit_code == 0, result.output


def lines_of(block: str) -> list[list[str]]:
    return [line.split() for line in block.splitlines()]


@pytest.mark.e2e
def test_studies_list_shows_each_study_with_its_strategy_and_run_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    spec = served(tmp_path, monkeypatch, source)
    original = spec.read_text()
    run(in_study(spec, "ma-grid", "[1, 2]"))
    spec.write_text(original)
    run(in_study(spec, "ma-single", "1"))

    result = runner.invoke(app, ["studies", "list"])

    assert result.exit_code == 0, result.output
    assert lines_of(result.output) == [
        ["study", "strategy", "runs"],
        ["ma-grid", MA_CROSS, "2"],
        ["ma-single", MA_CROSS, "1"],
    ]


@pytest.mark.e2e
def test_report_study_shows_a_row_per_run_with_its_varying_params_and_headline_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ServedSource()
    source.serve(DAY, VALIDATION_DAY)
    spec = without_a_part(served(tmp_path, monkeypatch, source))
    run(in_study(spec, "ma-grid", "[1, 2]"))
    runs = ParquetResultStore(tmp_path / "data" / "results").runs()

    result = runner.invoke(app, ["report", "study", "ma-grid"])

    assert result.exit_code == 0, result.output
    blocks = result.output.strip().split("\n\n")
    assert [block.splitlines()[0] for block in blocks] == ["train", "validation"]
    for block, part in zip(blocks, ["train", "validation"], strict=True):
        header, *rows = lines_of(block)[1:]
        assert header[:2] == ["run_id", "fast"]
        assert {"net_return", "sharpe", "trade_count"} <= set(header)
        assert "slow" not in header
        ran = runs.loc[runs["part"] == part]
        assert [row[:2] for row in rows] == [
            [run_id, fast]
            for run_id, fast in zip(ran["run_id"], ["1", "2"], strict=True)
        ]


@pytest.mark.e2e
def test_report_of_an_unknown_study_names_the_known_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SBT2_DATA", str(tmp_path))
    store = ParquetResultStore(tmp_path / "results")
    for name in ("ma-grid", "ma-single"):
        store.new_study(StoredStudy(name, {"strategy": MA_CROSS}, ""))
    log = tmp_path / "sbt2.log"

    result = runner.invoke(app, ["--log-file", str(log), "report", "study", "nope"])

    assert result.exit_code == 1
    assert "known: ma-grid, ma-single" in log.read_text()
