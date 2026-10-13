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
venue = "deribit_option"
capital = "1 BTC"

[chain]
min_dte = 0
max_dte = 90
strike_band = "0.5"
"""
VENUES = """
[deribit_option]
name = "DERIBIT"
source = "deribit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "OPTION"
fee_model = { kind = "capped_option", config = { maker_rate = "0.0003", taker_rate = "0.0003", cap_rate = "0.125" } }
"""


def run_options(
    tmp_path: Path, catalog: Path, strategy: str
) -> tuple[ParquetResultStore, str]:
    """Runs the combo strategy ``strategy`` on the option ``catalog`` and
    returns the store of the run and its id."""
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC.replace("combo_strategies:OpenStrangle", strategy))
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog, max_chain_contracts=2_000))
    return store, sink.run_id
