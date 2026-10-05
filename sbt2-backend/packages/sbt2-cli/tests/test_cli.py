from pathlib import Path

import pytest
from launchers import PlainLauncher
from nautilus_trader.model import FundingRateUpdate
from served_source import INSTRUMENT_ID, ServedSource
from served_spec import DAY, NEXT_DAY, VALIDATION_DAY, served, without_a_part
from typer.testing import CliRunner

from sbt2 import cli
from sbt2.cli import app
from sbt2.core.data.sources import Gap
from sbt2.core.results import ParquetResultStore
from sbt2.core.run import Launcher, launcher_named

runner = CliRunner()
FAILING = """
from nautilus_trader.model import Bar, BarSpecification

from sbt2.core.strategy import NoParams, Strategy


class FailOnBar(Strategy[NoParams]):
    @classmethod
    def inputs(cls, params):
        return (BarSpecification.from_str("1-HOUR-LAST"),)

    def on_bar(self, bar: Bar) -> None:
        raise RuntimeError("strategy blew up")
"""
GiB = 2**30


def launchers_asked(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Records each name ``sbt2 run`` asks a launcher for, and has the run
    start its children with a ``PlainLauncher``."""
    names: list[str] = []

    def spy(name: str) -> Launcher:
        names.append(name)
        return PlainLauncher()

    monkeypatch.setattr(cli, "launcher_named", spy)
    return names


def run_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    return served(tmp_path, monkeypatch, source)


@pytest.mark.e2e
def test_a_missing_spec_fails_the_run_and_logs_why(tmp_path: Path) -> None:
    log = tmp_path / "sbt2.log"

    result = runner.invoke(
        app,
        ["--log-file", str(log), "run", str(tmp_path / "missing.toml")]
        + ["--data", str(tmp_path), "--config", str(tmp_path)],
    )

    assert result.exit_code == 1
    assert "run of" in log.read_text()
    assert "FileNotFoundError" in log.read_text()


@pytest.mark.e2e
def test_an_invalid_spec_stores_nothing(tmp_path: Path) -> None:
    spec = tmp_path / "spec.toml"
    spec.write_text('colour = "blue"\n')

    result = runner.invoke(
        app, ["run", str(spec), "--data", str(tmp_path), "--config", str(tmp_path)]
    )

    assert result.exit_code == 1
    assert "unknown keys colour" in result.output
    assert not (tmp_path / "results").exists()


@pytest.mark.e2e
def test_without_a_command_it_shows_the_commands() -> None:
    result = runner.invoke(app, [])

    assert "run" in result.output


@pytest.mark.e2e
def test_a_run_with_missing_data_fails_before_the_engine_starts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ServedSource()
    source.serve(DAY, DAY)
    spec = served(tmp_path, monkeypatch, source)
    log = tmp_path / "sbt2.log"

    result = runner.invoke(app, ["--log-file", str(log), "run", str(spec)])

    assert result.exit_code == 1
    assert "MissingDataError" in log.read_text()
    assert "BTCUSDT-LINEAR.BYBIT TradeTick 2024-01-02" in log.read_text()
    assert not (tmp_path / "data" / "results").exists()


@pytest.mark.e2e
def test_a_run_stores_the_known_gap_days_it_skipped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gap = Gap(INSTRUMENT_ID, FundingRateUpdate, NEXT_DAY)
    source = ServedSource(known_gaps=frozenset({gap}))
    source.serve(DAY, NEXT_DAY)
    source.withdraw(FundingRateUpdate, NEXT_DAY)
    spec = served(tmp_path, monkeypatch, source)

    result = runner.invoke(app, ["run", str(spec)])

    assert result.exit_code == 0, result.output
    [summary] = (
        ParquetResultStore(tmp_path / "data" / "results").runs().to_dict("records")
    )
    assert list(summary["known_gaps"]) == [str(gap)]


def failing(spec: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The spec, with a strategy that raises on its first bar."""
    (spec.parent / "failing.py").write_text(FAILING)
    monkeypatch.syspath_prepend(spec.parent)
    text = spec.read_text().split("[params]")[0]
    spec.write_text(text.replace("crossover:MovingAverageCross", "failing:FailOnBar"))
    return spec


@pytest.mark.e2e
def test_a_spec_without_a_part_stores_a_train_and_a_validation_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ServedSource()
    source.serve(DAY, VALIDATION_DAY)
    spec = without_a_part(served(tmp_path, monkeypatch, source))

    result = runner.invoke(app, ["run", str(spec)])

    assert result.exit_code == 0, result.output
    runs = ParquetResultStore(tmp_path / "data" / "results").runs()
    assert sorted(runs["part"]) == ["train", "validation"]


SUMMARY_HEADER = [
    "run_id",
    "strategy",
    "net_return",
    "annualized_return",
    "sharpe",
    "max_drawdown",
    "trade_count",
    "total_fees",
    "total_carry",
]


@pytest.mark.e2e
def test_run_prints_the_headline_metrics_per_part(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ServedSource()
    source.serve(DAY, VALIDATION_DAY)
    spec = without_a_part(served(tmp_path, monkeypatch, source))
    spec.write_text(spec.read_text().replace("fast = 1", "fast = [1, 2]"))

    result = runner.invoke(app, ["run", str(spec)])

    assert result.exit_code == 0, result.output
    runs = ParquetResultStore(tmp_path / "data" / "results").runs()
    tables = [block.splitlines() for block in result.stdout.strip().split("\n\n")]
    assert [table[0] for table in tables] == ["train", "validation"]
    for (part, header, *rows), (_, stored) in zip(
        tables, runs.groupby("part"), strict=True
    ):
        assert header.split() == SUMMARY_HEADER
        cells = [row.split() for row in rows]
        assert [row[0] for row in cells] == list(stored["run_id"]), part
        assert [row[6] for row in cells] == [
            str(each) for each in stored["trade_count"]
        ]


@pytest.mark.e2e
def test_every_run_is_preflighted_before_any_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    spec = without_a_part(served(tmp_path, monkeypatch, source))
    log = tmp_path / "sbt2.log"

    result = runner.invoke(app, ["--log-file", str(log), "run", str(spec)])

    assert result.exit_code == 1
    assert "MissingDataError" in log.read_text()
    assert not (tmp_path / "data" / "results").exists()


@pytest.mark.e2e
def test_a_failed_run_logs_its_run_id_and_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    spec = failing(served(tmp_path, monkeypatch, source), monkeypatch)
    log = tmp_path / "sbt2.log"

    result = runner.invoke(app, ["--log-file", str(log), "run", str(spec)])

    assert result.exit_code == 1
    [folder] = (tmp_path / "data" / "results" / "runs").iterdir()
    assert f"run {folder.name} failed" in log.read_text()
    assert f"its folder is {folder}" in log.read_text()
    assert "strategy blew up" in log.read_text()


@pytest.mark.e2e
def test_the_memory_options_set_each_runs_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launcher: PlainLauncher
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    spec = served(tmp_path, monkeypatch, source)

    result = runner.invoke(
        app, ["run", str(spec), "--memory-budget", "6G", "--memory-per-run", "3G"]
    )

    assert result.exit_code == 0, result.output
    assert launcher.caps == [3 * GiB]


@pytest.mark.e2e
def test_without_memory_options_each_run_is_capped_at_4g(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, launcher: PlainLauncher
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    spec = served(tmp_path, monkeypatch, source)

    result = runner.invoke(app, ["run", str(spec)])

    assert result.exit_code == 0, result.output
    assert launcher.caps == [4 * GiB]


@pytest.mark.e2e
def test_an_unreadable_memory_size_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["run", str(tmp_path / "spec.toml"), "--memory-per-run", "lots"]
        + ["--data", str(tmp_path), "--config", str(tmp_path)],
    )

    assert result.exit_code == 2
    assert "lots" in result.output


@pytest.mark.e2e
def test_a_budget_below_the_per_run_cap_fails_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    spec = served(tmp_path, monkeypatch, source)
    log = tmp_path / "sbt2.log"

    result = runner.invoke(
        app,
        ["--log-file", str(log), "run", str(spec)]
        + ["--memory-budget", "1G", "--memory-per-run", "2G"],
    )

    assert result.exit_code == 1
    assert "memory budget" in log.read_text()
    assert not (tmp_path / "data" / "results").exists()


@pytest.mark.e2e
def test_run_uses_the_uncapped_launcher_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    asked = launchers_asked(monkeypatch)

    result = runner.invoke(app, ["run", str(spec)])

    assert result.exit_code == 0, result.output
    assert asked == ["uncapped"]


@pytest.mark.e2e
def test_the_launcher_option_picks_the_systemd_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    asked = launchers_asked(monkeypatch)

    result = runner.invoke(app, ["run", str(spec), "--launcher", "systemd"])

    assert result.exit_code == 0, result.output
    assert asked == ["systemd"]


@pytest.mark.e2e
def test_run_with_an_unknown_launcher_starts_no_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    log = tmp_path / "sbt2.log"
    monkeypatch.setattr(cli, "launcher_named", launcher_named)

    result = runner.invoke(
        app, ["--log-file", str(log), "run", str(spec), "--launcher", "cgroup"]
    )

    assert result.exit_code == 1
    assert "UnknownLauncherError" in log.read_text()
    assert "cgroup" in log.read_text()
    assert not (tmp_path / "data" / "results").exists()
