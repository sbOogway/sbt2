import json
import uuid
from pathlib import Path

import pytest
from served_source import ServedSource
from served_spec import DAY, VALIDATION_DAY, served, without_a_part
from typer.testing import CliRunner

from sbt2 import spec
from sbt2.cli import app
from sbt2.results import ParquetResultStore

runner = CliRunner()
LIST_HEADER = [
    "run_id",
    "strategy",
    "part",
    "start",
    "end",
    "net_return",
    "sharpe",
    "max_drawdown",
    "trade_count",
]
MA_CROSS = "strategies.ma_cross:MovingAverageCross"


def stored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ParquetResultStore:
    """A store holding a train and a validation run of the served spec."""
    source = ServedSource()
    source.serve(DAY, VALIDATION_DAY)
    spec = without_a_part(served(tmp_path, monkeypatch, source))
    result = runner.invoke(app, ["run", str(spec)])
    assert result.exit_code == 0, result.output
    return ParquetResultStore(tmp_path / "data" / "results")


def unfinished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ParquetResultStore, str]:
    """A store holding the folder of a run that started but never finished."""
    spec_file = served(tmp_path, monkeypatch, ServedSource())
    store = ParquetResultStore(tmp_path / "data" / "results")
    [run_spec] = spec.load(spec_file)
    return store, store.new_run(run_spec).run_id


def spec_document(output: str) -> object:
    lines = output.splitlines()
    return json.loads("\n".join(lines[lines.index("{") :]))


def rows(output: str) -> list[list[str]]:
    return [line.split() for line in output.splitlines()]


@pytest.mark.e2e
def test_runs_list_shows_one_row_per_run_oldest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = stored(tmp_path, monkeypatch)
    oldest, newest = store.runs()["run_id"]

    result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 0, result.output
    header, first, second = rows(result.output)
    assert header == LIST_HEADER
    assert (first[0], first[1], first[2]) == (oldest, MA_CROSS, "train")
    assert (second[0], second[2]) == (newest, "validation")


@pytest.mark.e2e
def test_runs_list_filters_by_part(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored(tmp_path, monkeypatch)

    result = runner.invoke(app, ["runs", "list", "--part", "validation"])

    assert result.exit_code == 0, result.output
    _, only = rows(result.output)
    assert only[2] == "validation"


@pytest.mark.e2e
def test_runs_list_filters_by_strategy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stored(tmp_path, monkeypatch)

    matching = runner.invoke(app, ["runs", "list", "--strategy", MA_CROSS])
    other = runner.invoke(app, ["runs", "list", "--strategy", "other:Strategy"])

    assert len(rows(matching.output)) == 3
    assert other.exit_code == 0, other.output
    assert other.output.strip() == "no runs"


@pytest.mark.e2e
def test_runs_list_of_an_empty_store_says_so(tmp_path: Path) -> None:
    result = runner.invoke(app, ["runs", "list", "--data", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "no runs"


@pytest.mark.e2e
def test_runs_show_prints_the_summary_and_the_resolved_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = stored(tmp_path, monkeypatch)
    run_id = store.runs()["run_id"].iloc[0]

    result = runner.invoke(app, ["runs", "show", run_id])

    assert result.exit_code == 0, result.output
    summary = result.output.split("\n\n")[0].splitlines()
    fields = dict(line.split(maxsplit=1) for line in summary)
    assert fields["run_id"] == run_id
    assert fields["spec_hash"] == store.runs()["spec_hash"].iloc[0]
    assert "net_return" in fields
    assert spec_document(result.output) == store.spec(run_id)


@pytest.mark.e2e
def test_runs_show_of_a_failed_run_says_it_has_no_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, run_id = unfinished(tmp_path, monkeypatch)

    result = runner.invoke(app, ["runs", "show", run_id])

    assert result.exit_code == 0, result.output
    assert f"run {run_id} has no summary: it did not finish" in result.output
    assert spec_document(result.output) == store.spec(run_id)


@pytest.mark.e2e
def test_runs_show_of_an_unknown_run_fails(tmp_path: Path) -> None:
    log = tmp_path / "sbt2.log"

    result = runner.invoke(
        app,
        ["--log-file", str(log), "runs", "show", str(uuid.uuid7())]
        + ["--data", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "UnknownRunError" in log.read_text()


@pytest.mark.e2e
def test_runs_delete_asks_and_removes_the_run_on_yes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = stored(tmp_path, monkeypatch)
    run_id = store.runs()["run_id"].iloc[0]

    result = runner.invoke(app, ["runs", "delete", run_id], input="y\n")

    assert result.exit_code == 0, result.output
    assert f"delete run {run_id}?" in result.output
    assert not store.folder(run_id).exists()


@pytest.mark.e2e
def test_runs_delete_keeps_the_run_on_no(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = stored(tmp_path, monkeypatch)
    run_id = store.runs()["run_id"].iloc[0]

    result = runner.invoke(app, ["runs", "delete", run_id], input="n\n")

    assert result.exit_code == 1
    assert store.folder(run_id).exists()


@pytest.mark.e2e
def test_runs_delete_with_yes_does_not_ask(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = stored(tmp_path, monkeypatch)
    run_id = store.runs()["run_id"].iloc[0]

    result = runner.invoke(app, ["runs", "delete", run_id, "--yes"])

    assert result.exit_code == 0, result.output
    assert "?" not in result.output
    assert not store.folder(run_id).exists()


@pytest.mark.e2e
def test_runs_delete_removes_a_failed_runs_partial_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, run_id = unfinished(tmp_path, monkeypatch)

    result = runner.invoke(app, ["runs", "delete", run_id, "--yes"])

    assert result.exit_code == 0, result.output
    assert not store.folder(run_id).exists()


@pytest.mark.e2e
def test_runs_delete_of_an_unknown_run_fails(tmp_path: Path) -> None:
    log = tmp_path / "sbt2.log"

    result = runner.invoke(
        app,
        ["--log-file", str(log), "runs", "delete", str(uuid.uuid7()), "--yes"]
        + ["--data", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "UnknownRunError" in log.read_text()
