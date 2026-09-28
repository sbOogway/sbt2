from pathlib import Path

from typer.testing import CliRunner

from sbt2.cli import app

runner = CliRunner()


def test_a_missing_spec_fails_the_run_and_logs_why(tmp_path: Path) -> None:
    log = tmp_path / "sbt2.log"

    result = runner.invoke(
        app, ["--log-file", str(log), "run", str(tmp_path / "missing.toml")]
    )

    assert result.exit_code == 1
    assert "run of" in log.read_text()
    assert "FileNotFoundError" in log.read_text()


def test_an_invalid_spec_stores_nothing(tmp_path: Path) -> None:
    spec = tmp_path / "spec.toml"
    spec.write_text('colour = "blue"\n')

    result = runner.invoke(app, ["run", str(spec), "--data", str(tmp_path)])

    assert result.exit_code == 1
    assert "unknown keys colour" in result.output
    assert not (tmp_path / "results").exists()


def test_without_a_command_it_shows_the_commands() -> None:
    result = runner.invoke(app, [])

    assert "run" in result.output
