from dataclasses import dataclass
from pathlib import Path

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "combo_strategies:OpenStrangle"
instruments = ["BTC-OPTIONS.DERIBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
execution = { fee_model = { kind = "capped_option", config = { maker_rate = "0.0003", taker_rate = "0.0003", cap_rate = "0.125" } } }
capital = "1 BTC"

[chain]
min_dte = 0
max_dte = 90
strike_band = "0.5"
"""


@dataclass(frozen=True)
class Scenario:
    """A combo strategy and the spec tables, such as ``[risk.short_premium]``,
    appended to the spec of its run."""

    strategy: str
    tables: str = ""


def run_options(
    tmp_path: Path, catalog: Path, scenario: str | Scenario
) -> tuple[ParquetResultStore, str]:
    """Runs ``scenario`` (a combo strategy, alone or with spec tables) on the
    option ``catalog`` and returns the store of the run and its id."""
    chosen = Scenario(scenario) if isinstance(scenario, str) else scenario
    spec = tmp_path / "spec.toml"
    spec.write_text(
        SPEC.replace("combo_strategies:OpenStrangle", chosen.strategy) + chosen.tables
    )
    [resolved] = load(spec)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog, max_chain_contracts=2_000))
    return store, sink.run_id


def run_two_chains(
    tmp_path: Path, catalog: Path, scenario: str | Scenario
) -> tuple[ParquetResultStore, str]:
    """Like ``run_options`` with the BTC and the ETH chain of the catalog and a
    capital of 1 BTC and 20 ETH."""
    chosen = Scenario(scenario) if isinstance(scenario, str) else scenario
    spec = tmp_path / "spec.toml"
    text = SPEC.replace("combo_strategies:OpenStrangle", chosen.strategy)
    text = text.replace(
        '["BTC-OPTIONS.DERIBIT"]', '["BTC-OPTIONS.DERIBIT", "ETH-OPTIONS.DERIBIT"]'
    )
    text = text.replace('capital = "1 BTC"', 'capital = ["1 BTC", "20 ETH"]')
    spec.write_text(text + chosen.tables)
    [resolved] = load(spec)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog, max_chain_contracts=2_000))
    return store, sink.run_id
