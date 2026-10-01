"""Specs, data and setups for running batches on served data."""

from datetime import date
from pathlib import Path
from typing import Any

from served_source import ServedSource

from sbt2.data.sources import Gap
from sbt2.results import ParquetResultStore
from sbt2.run import BatchSetup, DataFolders, Launcher, Memory, RunSettings
from sbt2.spec import ResolvedRunSpec, load

SPEC = """
strategy = "run_strategies:BuyThenSell"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
venue = "served_linear"
capital = "10000 USDT"
"""
VENUES = """
[served_linear]
name = "BYBIT"
source = "served"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
default_leverage = "10"
fee_model = { path = "nautilus_trader.execution:MakerTakerFeeModel", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }
"""
DAY = date(2024, 1, 1)
NEXT_DAY = date(2024, 1, 2)
GiB = 2**30


def resolved(tmp_path: Path, **overrides: Any) -> ResolvedRunSpec:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)
    venues.write_text(VENUES)
    [resolved] = load(spec, overrides, venues)
    return resolved


def served(known_gaps: frozenset[Gap] = frozenset()) -> ServedSource:
    source = ServedSource(known_gaps)
    source.serve(DAY, NEXT_DAY)
    return source


def setup(
    tmp_path: Path, launcher: Launcher, source: ServedSource | None = None
) -> BatchSetup:
    data = DataFolders(tmp_path / "raw", tmp_path / "catalog")
    return BatchSetup(
        store=ParquetResultStore(tmp_path / "results"),
        sources=lambda _name: source or served(),
        folders=data,
        settings=RunSettings(data.catalog),
        launcher=launcher,
        memory=Memory(budget=2 * GiB, per_run=GiB),
    )


def summaries(tmp_path: Path) -> dict[str, dict[str, Any]]:
    runs = ParquetResultStore(tmp_path / "results").runs()
    return {each["run_id"]: each for each in runs.to_dict("records")}
