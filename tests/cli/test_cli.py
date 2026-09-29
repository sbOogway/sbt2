from datetime import date
from pathlib import Path

import pytest
from nautilus_trader.model import FundingRateUpdate
from served_source import INSTRUMENT_ID, ServedSource
from typer.testing import CliRunner

from sbt2.cli import app
from sbt2.data import sources
from sbt2.data.sources import Gap
from sbt2.results import ParquetResultStore, Provenance

runner = CliRunner()
SPEC = """
strategy = "strategies.ma_cross:MovingAverageCross"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
venue = "served_linear"
capital = "10000 USDT"

[params]
fast = 1
slow = 2
"""
VENUES = """
[served_linear]
name = "BYBIT"
source = "served"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
fee_model = { path = "nautilus_trader.execution:MakerTakerFeeModel", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }
"""
DAY = date(2024, 1, 1)
NEXT_DAY = date(2024, 1, 2)


def served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: ServedSource
) -> Path:
    """A spec run from ``tmp_path``, whose venue's data comes from ``source``."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "venues.toml").write_text(VENUES)
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sources, "source", lambda name, config: source)
    monkeypatch.setattr(
        Provenance, "of_repo", lambda repo: Provenance("abc123", git_dirty=False)
    )
    return spec


@pytest.mark.e2e
def test_a_missing_spec_fails_the_run_and_logs_why(tmp_path: Path) -> None:
    log = tmp_path / "sbt2.log"

    result = runner.invoke(
        app, ["--log-file", str(log), "run", str(tmp_path / "missing.toml")]
    )

    assert result.exit_code == 1
    assert "run of" in log.read_text()
    assert "FileNotFoundError" in log.read_text()


@pytest.mark.e2e
def test_an_invalid_spec_stores_nothing(tmp_path: Path) -> None:
    spec = tmp_path / "spec.toml"
    spec.write_text('colour = "blue"\n')

    result = runner.invoke(app, ["run", str(spec), "--data", str(tmp_path)])

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
