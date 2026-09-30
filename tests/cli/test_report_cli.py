import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import CryptoPerpetual, MarkPriceUpdate, Price
from plotted import Plotted, plotted
from served_source import ServedSource, perpetual
from served_spec import DAY, NEXT_DAY, VALIDATION_DAY, served, without_a_part
from typer.testing import CliRunner

from sbt2.cli import app
from sbt2.data.catalog import CatalogWriter, DayFile
from sbt2.results import ParquetResultStore

runner = CliRunner()
ETH = "ETHUSDT-LINEAR.BYBIT"
BENCHMARKED = """
from sbt2.results import BuyAndHold
from strategies.ma_cross import MovingAverageCross


class BenchmarkedCross(MovingAverageCross):
    benchmark = BuyAndHold()
"""
MA_CROSS = "strategies.ma_cross:MovingAverageCross"
HOUR_NS = 3_600_000_000_000
DAY_NS = 24 * HOUR_NS


def stored_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, strategy: str = MA_CROSS
) -> str:
    """The run_id of a train run of the served spec under ``strategy``."""
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    spec = served(tmp_path, monkeypatch, source)
    spec.write_text(spec.read_text().replace(MA_CROSS, strategy))
    result = runner.invoke(app, ["run", str(spec)])
    assert result.exit_code == 0, result.output
    [run_id] = ParquetResultStore(tmp_path / "data" / "results").runs()["run_id"]
    return run_id


def benchmarked_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A run of a strategy whose default benchmark is buy-and-hold."""
    (tmp_path / "benchmarked.py").write_text(BENCHMARKED)
    monkeypatch.syspath_prepend(tmp_path)
    return stored_run(tmp_path, monkeypatch, "benchmarked:BenchmarkedCross")


def with_rising_eth(tmp_path: Path) -> None:
    """ETH's mark price in the catalog, rising every hour of the served days."""
    writer = CatalogWriter(tmp_path / "data" / "catalog")
    eth = eth_perpetual()
    writer.write_instrument(eth)
    start = dt_to_unix_nanos(datetime(DAY.year, DAY.month, DAY.day, tzinfo=UTC))
    for day in range(2):
        first = start + day * DAY_NS
        records = [
            MarkPriceUpdate(eth.id, Price(3000 * 1.01 ** (24 * day + hour), 2), ts, ts)
            for hour in range(24)
            for ts in [first + hour * HOUR_NS]
        ]
        bounds = (first, first + DAY_NS - 1)
        writer.write(DayFile(MarkPriceUpdate, eth, bounds), records)


def eth_perpetual() -> CryptoPerpetual:
    fields = CryptoPerpetual.to_dict(perpetual())
    changes = {"id": ETH, "raw_symbol": "ETHUSDT", "base_currency": "ETH"}
    return CryptoPerpetual.from_dict({**fields, **changes})


def report(*arguments: str, log: Path | None = None) -> Any:
    logging = [] if log is None else ["--log-file", str(log)]
    return runner.invoke(app, [*logging, "report", *arguments])


def drawn(path: Path) -> Plotted:
    return plotted(path.read_text())


def run_folder(tmp_path: Path, run_id: str) -> Path:
    return tmp_path / "data" / "results" / "runs" / run_id


def statistic_names(figure: Plotted) -> list[str]:
    [table] = [
        each
        for each in figure.of_type("table")
        if each["header"]["values"] == ["<b>Metric</b>", "<b>Value</b>"]
    ]
    return table["cells"]["values"][0]


@pytest.mark.e2e
def test_report_tearsheet_writes_into_the_run_folder_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = stored_run(tmp_path, monkeypatch)
    log = tmp_path / "sbt2.log"

    result = report("tearsheet", run_id, log=log)

    assert result.exit_code == 0, result.output
    written = run_folder(tmp_path, run_id) / "tearsheet.html"
    assert "Plotly.newPlot(" in written.read_text()
    assert str(Path("data") / "results" / "runs" / run_id) in log.read_text()


@pytest.mark.e2e
def test_report_tearsheet_writes_to_the_given_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = stored_run(tmp_path, monkeypatch)

    result = report("tearsheet", run_id, "--output", "x.html")

    assert result.exit_code == 0, result.output
    assert "Plotly.newPlot(" in (tmp_path / "x.html").read_text()
    assert not (run_folder(tmp_path, run_id) / "tearsheet.html").exists()


@pytest.mark.e2e
def test_the_strategy_default_benchmark_is_overlaid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = benchmarked_run(tmp_path, monkeypatch)

    result = report("tearsheet", run_id, "--output", "sheet.html")

    assert result.exit_code == 0, result.output
    assert drawn(tmp_path / "sheet.html").named("BuyAndHold")


@pytest.mark.e2e
def test_the_benchmark_option_overrides_the_strategy_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = benchmarked_run(tmp_path, monkeypatch)
    with_rising_eth(tmp_path)

    default = report("tearsheet", run_id, "--output", "btc.html")
    result = report(
        "tearsheet",
        run_id,
        "--output",
        "eth.html",
        "--benchmark",
        f"buy-and-hold:{ETH}",
    )

    assert default.exit_code == 0, default.output
    assert result.exit_code == 0, result.output
    btc = drawn(tmp_path / "btc.html").trace("BuyAndHold")["y"]
    eth = drawn(tmp_path / "eth.html").trace("BuyAndHold")["y"]
    assert eth[-1] > 1.1 * btc[-1]


@pytest.mark.e2e
def test_benchmark_none_leaves_no_overlay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = benchmarked_run(tmp_path, monkeypatch)

    result = report("tearsheet", run_id, "--output", "x.html", "--benchmark", "none")

    assert result.exit_code == 0, result.output
    figure = drawn(tmp_path / "x.html")
    assert not figure.named("BuyAndHold")
    assert "Beta" not in statistic_names(figure)


@pytest.mark.e2e
def test_an_unknown_benchmark_fails_listing_the_known_ones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = stored_run(tmp_path, monkeypatch)
    log = tmp_path / "sbt2.log"

    result = report("tearsheet", run_id, "--benchmark", "sp500", log=log)

    assert result.exit_code == 1
    assert "known: buy-and-hold, equal-weight, external, none" in log.read_text()


@pytest.mark.e2e
def test_report_of_an_unknown_run_fails(tmp_path: Path) -> None:
    run_id = str(uuid.uuid7())
    log = tmp_path / "sbt2.log"

    result = report("tearsheet", run_id, "--data", str(tmp_path), log=log)

    assert result.exit_code == 1
    assert f"tearsheet of run {run_id} failed" in log.read_text()
    assert "UnknownRunError" in log.read_text()


@pytest.mark.e2e
def test_a_failed_run_gets_no_tearsheet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = stored_run(tmp_path, monkeypatch)
    (run_folder(tmp_path, run_id) / "summary.parquet").unlink()
    log = tmp_path / "sbt2.log"

    result = report("tearsheet", run_id, log=log)

    assert result.exit_code == 1
    assert "MissingTableError" in log.read_text()


@pytest.mark.e2e
def test_a_batch_on_the_synthetic_catalog_gets_a_tearsheet_with_a_benchmark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = stored_run(tmp_path, monkeypatch)

    result = report("tearsheet", run_id, "--benchmark", "buy-and-hold")

    assert result.exit_code == 0, result.output
    figure = drawn(run_folder(tmp_path, run_id) / "tearsheet.html")
    assert figure.named("BuyAndHold")
    names = statistic_names(figure)
    assert "Alpha (365 days)" in names
    assert "Beta" in names


def stored_parts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ParquetResultStore:
    """A store holding a train and a validation run of the served spec."""
    source = ServedSource()
    source.serve(DAY, VALIDATION_DAY)
    spec = without_a_part(served(tmp_path, monkeypatch, source))
    result = runner.invoke(app, ["run", str(spec)])
    assert result.exit_code == 0, result.output
    return ParquetResultStore(tmp_path / "data" / "results")


def stored_batch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ParquetResultStore:
    """A store holding one batch of two train runs, fast 1 and fast 2."""
    source = ServedSource()
    source.serve(DAY, NEXT_DAY)
    spec = served(tmp_path, monkeypatch, source)
    spec.write_text(spec.read_text().replace("fast = 1", "fast = [1, 2]"))
    result = runner.invoke(app, ["run", str(spec)])
    assert result.exit_code == 0, result.output
    return ParquetResultStore(tmp_path / "data" / "results")


def lines_of(block: str) -> list[list[str]]:
    return [line.split() for line in block.splitlines()]


@pytest.mark.e2e
def test_report_parts_prints_each_part_and_the_degradation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = stored_parts(tmp_path, monkeypatch)
    train, validation = store.runs()["run_id"]

    result = report("parts", train)

    assert result.exit_code == 0, result.output
    parts, change = result.output.strip().split("\n\n")
    header, *rows = lines_of(parts)
    assert header[:2] == ["part", "run_id"]
    assert {"net_return", "sharpe", "trade_count"} <= set(header)
    assert [row[:2] for row in rows] == [["train", train], ["validation", validation]]
    metric_header, *metrics = change.splitlines()
    assert metric_header.split()[:3] == ["metric", "train", "validation"]
    assert "train → validation %" in metric_header
    assert {line.split()[0] for line in metrics} >= {"net_return", "sharpe"}


@pytest.mark.e2e
def test_report_parts_of_an_unknown_run_fails(tmp_path: Path) -> None:
    run_id = str(uuid.uuid7())
    log = tmp_path / "sbt2.log"

    result = report("parts", run_id, "--data", str(tmp_path), log=log)

    assert result.exit_code == 1
    assert "UnknownRunError" in log.read_text()


@pytest.mark.e2e
def test_report_batch_prints_the_batch_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = stored_batch(tmp_path, monkeypatch)
    runs = store.runs()
    [batch_id] = set(runs["batch_id"])

    result = report("batch", batch_id)

    assert result.exit_code == 0, result.output
    header, *rows = lines_of(result.output)
    assert header[:2] == ["run_id", "fast"]
    assert "slow" not in header
    assert "net_return" in header
    assert [row[:2] for row in rows] == [
        [run_id, fast] for run_id, fast in zip(runs["run_id"], ["1", "2"], strict=True)
    ]


@pytest.mark.e2e
def test_report_batch_of_an_unknown_batch_fails(tmp_path: Path) -> None:
    log = tmp_path / "sbt2.log"

    result = report("batch", str(uuid.uuid7()), "--data", str(tmp_path), log=log)

    assert result.exit_code == 1
    assert "UnknownBatchError" in log.read_text()
