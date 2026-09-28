import logging
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from nautilus_trader.model import Money
from synthetic_catalog import START, build_catalog

from sbt2.results import ParquetResultStore, Provenance
from sbt2.run import BacktestError, RunSettings, execute
from sbt2.spec import ResolvedRunSpec, load

SPEC = """
strategy = "run_strategies:BuyThenSell"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
start = 2024-01-01T02:00:00
end = 2024-01-03
venue = "test_linear"
capital = "10000 USDT"
"""
VENUES = """
[test_linear]
name = "BYBIT"
source = "bybit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
default_leverage = "10"
fee_model = { path = "nautilus_trader.execution:MakerTakerFeeModel", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }
"""
TAKER_FEE = 0.00055 * 50_000
FUNDING = -5.0


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("catalog")
    build_catalog(path)
    return path


def resolved(tmp_path: Path, **overrides: Any) -> ResolvedRunSpec:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)
    venues.write_text(VENUES)
    return load(spec, overrides, venues)


def run(
    tmp_path: Path, catalog: Path, **overrides: Any
) -> tuple[ParquetResultStore, str]:
    spec = resolved(tmp_path, **overrides)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(spec, Provenance("abc123", git_dirty=False))
    execute(spec, sink, RunSettings(catalog))
    return store, sink.run_id


def amounts(frame: pd.DataFrame, column: str) -> list[float]:
    return [Money.from_str(each).as_double() for each in frame[column]]


@pytest.mark.integration
def test_a_finished_run_is_listed_with_its_headline_metrics(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog)

    [summary] = store.runs().to_dict("records")
    assert summary["run_id"] == run_id
    assert summary["trade_count"] == 2
    assert summary["total_fees"] == pytest.approx(2 * TAKER_FEE)
    assert summary["total_carry"] == pytest.approx(2 * FUNDING)


@pytest.mark.integration
def test_the_carry_ledger_holds_the_venue_funding_payments(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog)

    carry = store.load(run_id, "carry")
    assert amounts(carry, "pnl_change") == [FUNDING, FUNDING]
    assert list(carry["ts_event"].dt.hour) == [8, 16]


@pytest.mark.integration
def test_funding_paid_before_a_reversal_stays_in_the_carry_ledger(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog, strategy="run_strategies:BuyThenReverse")

    carry = store.load(run_id, "carry")
    assert amounts(carry, "pnl_change") == [FUNDING, FUNDING, *[-FUNDING] * 3]
    assert len(store.load(run_id, "positions")) == 2


@pytest.mark.integration
def test_equity_ends_at_the_balance_less_fees_and_funding(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog)

    equity = store.load(run_id, "equity")
    assert equity["total_equity"].iloc[-1] == pytest.approx(
        10_000 - 2 * TAKER_FEE + 2 * FUNDING
    )


@pytest.mark.integration
def test_nautilus_reports_are_stored(tmp_path: Path, catalog: Path) -> None:
    store, run_id = run(tmp_path, catalog)

    assert len(store.load(run_id, "fills")) == 2
    assert len(store.load(run_id, "orders")) == 2
    assert len(store.load(run_id, "positions")) == 1
    assert not store.load(run_id, "account").empty


@pytest.mark.integration
def test_no_order_fills_during_warmup(tmp_path: Path, catalog: Path) -> None:
    store, run_id = run(tmp_path, catalog)

    fills = store.load(run_id, "fills")
    assert pd.to_datetime(fills["ts_event"], utc=True).min() >= START.replace(hour=2)


@pytest.mark.integration
def test_chunked_streaming_gives_the_same_result(tmp_path: Path, catalog: Path) -> None:
    spec = resolved(tmp_path)
    store = ParquetResultStore(tmp_path / "results")
    for chunk_size in (100, 1_000_000):
        sink = store.new_run(spec, Provenance("abc123", git_dirty=False))
        execute(spec, sink, RunSettings(catalog, chunk_size=chunk_size))

    summaries = store.runs().drop(columns="run_id")
    pd.testing.assert_series_equal(
        summaries.iloc[0], summaries.iloc[1], check_names=False
    )


@pytest.mark.integration
def test_a_strategy_error_fails_the_run_without_a_summary(
    tmp_path: Path, catalog: Path
) -> None:
    with pytest.raises(BacktestError, match="strategy blew up") as failure:
        run(tmp_path, catalog, strategy="run_strategies:FailOnBar")

    assert isinstance(failure.value.__cause__, RuntimeError)
    assert ParquetResultStore(tmp_path / "results").runs().empty


@pytest.mark.integration
def test_invalid_strategy_params_fail_the_run(tmp_path: Path, catalog: Path) -> None:
    spec = resolved(tmp_path)
    broken = replace(spec, strategy=replace(spec.strategy, params={"hold_bars": "x"}))
    sink = ParquetResultStore(tmp_path / "results").new_run(
        broken, Provenance("abc123", git_dirty=False)
    )

    with pytest.raises(BacktestError, match="hold_bars"):
        execute(broken, sink, RunSettings(catalog))


@pytest.mark.integration
def test_the_run_is_logged(
    tmp_path: Path, catalog: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger="sbt2.run"):
        _, run_id = run(tmp_path, catalog)

    assert f"run {run_id} finished" in caplog.messages


@pytest.mark.integration
def test_a_catalog_without_the_instruments_fails_the_run(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(BacktestError, match="No instruments found"):
        run(tmp_path, empty)
