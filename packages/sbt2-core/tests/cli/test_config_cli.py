from pathlib import Path

import pytest
from served_source import ServedSource
from served_spec import DAY, NEXT_DAY, VENUES, served
from typer.testing import CliRunner

from sbt2.core.cli import app
from sbt2.core.results import ParquetResultStore

runner = CliRunner()
TAKER_RATE = "0.00055"


def run_spec(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    return served(tmp_path, monkeypatch, source)


def config_folder(folder: Path, taker_rate: str) -> Path:
    """A config folder whose venue charges ``taker_rate``."""
    folder.mkdir(exist_ok=True)
    (folder / "venues.toml").write_text(VENUES.replace(TAKER_RATE, taker_rate))
    return folder


def taker_rates(tmp_path: Path) -> list[str]:
    """The taker rate in each stored run's spec, oldest run first."""
    store = ParquetResultStore(tmp_path / "data" / "results")
    return [
        store.spec(run_id)["venue"]["fee_model"]["config"]["taker_rate"]
        for run_id in store.runs()["run_id"]
    ]


@pytest.mark.e2e
def test_run_reads_the_venues_from_sbt2_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    monkeypatch.setenv("SBT2_CONFIG", str(config_folder(tmp_path / "c", "0.0042")))

    result = runner.invoke(app, ["run", str(spec)])

    assert result.exit_code == 0, result.output
    assert taker_rates(tmp_path) == ["0.0042"]


@pytest.mark.e2e
def test_the_config_option_wins_over_sbt2_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    a = config_folder(tmp_path / "a", "0.0011")
    b = config_folder(tmp_path / "b", "0.0022")
    monkeypatch.setenv("SBT2_CONFIG", str(a))

    result = runner.invoke(app, ["run", str(spec), "--config", str(b)])

    assert result.exit_code == 0, result.output
    assert taker_rates(tmp_path) == ["0.0022"]


@pytest.mark.e2e
def test_an_edited_venue_applies_to_the_next_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    folder = config_folder(tmp_path / "c", "0.0011")
    first = runner.invoke(app, ["run", str(spec), "--config", str(folder)])
    config_folder(folder, "0.0022")

    second = runner.invoke(app, ["run", str(spec), "--config", str(folder)])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert taker_rates(tmp_path) == ["0.0011", "0.0022"]


@pytest.mark.e2e
def test_run_with_a_config_folder_without_venues_fails_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = run_spec(tmp_path, monkeypatch)
    empty, log = tmp_path / "empty", tmp_path / "sbt2.log"
    empty.mkdir()

    result = runner.invoke(
        app, ["--log-file", str(log), "run", str(spec), "--config", str(empty)]
    )

    assert result.exit_code == 1, result.output
    assert str(empty / "venues.toml") in log.read_text()
    assert not (tmp_path / "data" / "results").exists()
