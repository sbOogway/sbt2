import json
import subprocess
import time
from datetime import timedelta
from pathlib import Path
from typing import override

import pytest
from launchers import spawned
from served_source import ServedSource
from served_spec import DAY, NEXT_DAY, VALIDATION_DAY, served, without_a_part
from typer.testing import CliRunner

from sbt2.core import cli
from sbt2.core.cli import app
from sbt2.core.results import ParquetResultStore
from sbt2.core.run import SystemdScope

runner = CliRunner()
GiB = 2**30
MA_CROSS = "sbt2.strategies.ma_cross:MovingAverageCross"
CAPPED = ["--memory-budget", "2G", "--memory-per-run", "1G"]
PAIRS = {(1, 3), (1, 4), (2, 3), (2, 4)}
HOG = """
import time
from dataclasses import dataclass

from nautilus_trader.model import Bar, BarSpecification

from sbt2.core.strategy import Strategy


@dataclass(frozen=True)
class HogParams:
    megabytes: int = 0
    seconds: float = 0


class Hog(Strategy[HogParams]):
    Params = HogParams

    @classmethod
    def inputs(cls, params):
        return (BarSpecification.from_str("1-HOUR-LAST"),)

    def on_bar(self, bar: Bar) -> None:
        # Writing the bytes, rather than bytearray(n), makes every page resident.
        self.block = b"x" * (self.params.megabytes * 2**20)
        time.sleep(self.params.seconds)
"""
HOGGING = """
[params]
megabytes = [2048, 1]
seconds = 60
"""
PARTS = {
    "train": ("2024-01-01T02:00:00+00:00", "2024-01-03T00:00:00+00:00"),
    "validation": ("2024-01-03T00:00:00+00:00", "2024-01-04T00:00:00+00:00"),
}


class CountingScope(SystemdScope):
    """Records each child's cap and the most children alive at once."""

    def __init__(self, started: list[subprocess.Popen[bytes]]) -> None:
        self.started = started
        self.caps: list[int] = []
        self.most_alive = 0

    @override
    def cap(self, run_id: str, pid: int, memory_max: int) -> None:
        super().cap(run_id, pid, memory_max)
        self.caps.append(memory_max)
        alive = sum(each.poll() is None for each in self.started)
        self.most_alive = max(self.most_alive, alive)


@pytest.fixture(autouse=True)
def launcher(monkeypatch: pytest.MonkeyPatch) -> CountingScope:
    scope = CountingScope(spawned(monkeypatch))
    monkeypatch.setattr(cli, "launcher_for", lambda _: scope)
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


def hogging(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A spec of two train runs at once: one allocates past its cap, the other
    lingers."""
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    spec = served(tmp_path, monkeypatch, source)
    (tmp_path / "hog.py").write_text(HOG)
    monkeypatch.syspath_prepend(tmp_path)
    text = spec.read_text().split("[params]")[0]
    spec.write_text(text.replace(MA_CROSS, "hog:Hog") + HOGGING)
    return spec


def run_folders(tmp_path: Path) -> dict[int, Path]:
    """Each run's folder, by the megabytes its spec allocates."""
    folders = (tmp_path / "data" / "results" / "runs").iterdir()
    return {
        json.loads((each / "spec.json").read_text())["strategy"]["params"][
            "megabytes"
        ]: each
        for each in folders
    }


def scope_state(run_id: str) -> str:
    show = ["systemctl", "--user", "show", f"sbt2-{run_id}.scope"]
    command = [*show, "--property=ActiveState", "--value"]
    shown = subprocess.run(command, capture_output=True, text=True, check=False)
    return shown.stdout.strip()


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

    assert shown == dict.fromkeys(PARTS, PAIRS)


@pytest.mark.e2e
@pytest.mark.systemd
def test_a_run_over_its_cap_fails_the_batch_with_an_out_of_memory_error_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = hogging(tmp_path, monkeypatch)
    log = tmp_path / "sbt2.log"

    result = runner.invoke(app, ["--log-file", str(log), "run", str(spec), *CAPPED])

    assert result.exit_code == 1
    hog = run_folders(tmp_path)[2048]
    logged = log.read_text()
    assert "OutOfMemoryError" in logged
    assert f"run {hog.name} failed: it ran out of memory over its 1G cap" in logged
    assert f"its folder is {hog}" in logged


@pytest.mark.e2e
@pytest.mark.systemd
def test_a_run_over_its_cap_writes_no_summary_and_stops_the_other_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = hogging(tmp_path, monkeypatch)
    started = time.monotonic()

    result = runner.invoke(app, ["run", str(spec), *CAPPED])

    assert result.exit_code == 1
    assert time.monotonic() - started < 30
    assert runner.invoke(app, ["runs", "list"]).output.strip() == "no runs"
    folders = run_folders(tmp_path).values()
    assert len(folders) == 2
    assert "active" not in [scope_state(each.name) for each in folders]
