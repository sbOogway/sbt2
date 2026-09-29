import json
import subprocess
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest
from served_source import ServedSource
from served_spec import DAY, VALIDATION_DAY, served, without_a_part
from typer.testing import CliRunner

from sbt2 import cli
from sbt2.cli import app
from sbt2.results import ParquetResultStore
from sbt2.run import SystemdScope

runner = CliRunner()
GiB = 2**30
CAPPED = ["--memory-budget", "2G", "--memory-per-run", "1G"]
PAIRS = {(1, 3), (1, 4), (2, 3), (2, 4)}
PARTS = {
    "train": ("2024-01-01T02:00:00+00:00", "2024-01-03T00:00:00+00:00"),
    "validation": ("2024-01-03T00:00:00+00:00", "2024-01-04T00:00:00+00:00"),
}


class CountingScope(SystemdScope):
    """Records each child's cap and the most children alive at once."""

    def __init__(self) -> None:
        self.started: list[subprocess.Popen[bytes]] = []
        self.caps: list[int] = []
        self.most_alive = 0

    def start(
        self, run_id: str, command: Sequence[str], memory_max: int
    ) -> subprocess.Popen[bytes]:
        child = super().start(run_id, command, memory_max)
        self.started.append(child)
        self.caps.append(memory_max)
        alive = sum(each.poll() is None for each in self.started)
        self.most_alive = max(self.most_alive, alive)
        return child


@pytest.fixture(autouse=True)
def launcher(monkeypatch: pytest.MonkeyPatch) -> CountingScope:
    scope = CountingScope()
    monkeypatch.setattr(cli, "SystemdScope", lambda: scope)
    return scope


def swept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ParquetResultStore:
    """A store holding every (fast, slow) pair of the served spec, on each part.

    The data starts a day early, for the slow averages' warm-up."""
    source = ServedSource()
    source.serve(DAY - timedelta(days=1), VALIDATION_DAY)
    spec = without_a_part(served(tmp_path, monkeypatch, source))
    spec.write_text(
        spec.read_text().replace("fast = 1\nslow = 2", "fast = [1, 2]\nslow = [3, 4]")
    )
    result = runner.invoke(app, ["run", str(spec), *CAPPED])
    assert result.exit_code == 0, result.output
    return ParquetResultStore(tmp_path / "data" / "results")


def pair(params: dict[str, object]) -> tuple[object, object]:
    return params["fast"], params["slow"]


def listed(output: str) -> list[dict[str, str]]:
    header, *body = (line.split() for line in output.splitlines())
    return [dict(zip(header, row, strict=True)) for row in body]


def summary_fields(output: str) -> dict[str, str]:
    summary = output.split("\n\n")[0].splitlines()
    return dict(line.split(maxsplit=1) for line in summary)


def resolved_spec(output: str) -> object:
    return json.loads(output[output.index("\n{") :])


@pytest.mark.e2e
@pytest.mark.systemd
def test_every_combination_runs_on_train_and_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = swept(tmp_path, monkeypatch)

    runs = store.runs().to_dict("records")

    assert len(runs) == 8
    for part in PARTS:
        pairs = [
            pair(json.loads(each["params"])) for each in runs if each["part"] == part
        ]
        assert sorted(pairs) == sorted(PAIRS)


@pytest.mark.e2e
@pytest.mark.systemd
def test_the_runs_go_budget_over_per_run_at_a_time_each_capped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launcher: CountingScope
) -> None:
    swept(tmp_path, monkeypatch)

    assert len(launcher.started) == 8
    assert launcher.most_alive == 2
    assert launcher.caps == [GiB] * 8


@pytest.mark.e2e
@pytest.mark.systemd
def test_runs_list_shows_each_run_with_its_part_and_dates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    swept(tmp_path, monkeypatch)

    result = runner.invoke(app, ["runs", "list"])

    assert result.exit_code == 0, result.output
    rows = listed(result.output)
    assert len(rows) == 8
    for part, (start, end) in PARTS.items():
        dates = [(row["start"], row["end"]) for row in rows if row["part"] == part]
        assert dates == [(start, end)] * 4


@pytest.mark.e2e
@pytest.mark.systemd
def test_runs_show_gives_each_run_its_params_split_and_spec_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = swept(tmp_path, monkeypatch)
    shown = {part: set() for part in PARTS}

    for run in store.runs().to_dict("records"):
        result = runner.invoke(app, ["runs", "show", run["run_id"]])
        assert result.exit_code == 0, result.output
        fields = summary_fields(result.output)
        assert fields["spec_hash"] == run["spec_hash"]
        assert json.loads(fields["split"]) == json.loads(run["split"])
        assert resolved_spec(result.output) == store.spec(run["run_id"])
        shown[fields["part"]].add(pair(json.loads(fields["params"])))

    assert shown == {part: PAIRS for part in PARTS}
