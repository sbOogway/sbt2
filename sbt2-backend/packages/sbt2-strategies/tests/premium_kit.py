"""Runs a short premium strategy on the synthetic option catalogs."""

from pathlib import Path
from typing import Any

import pandas as pd
from option_catalog import write_dvol

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "sbt2.strategies.short_premium:{name}"
instruments = ["BTC-OPTIONS.DERIBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = {{ validation_start = 2024-01-03, test_start = 2024-01-04 }}
part = "train"
venue = "deribit_option"
capital = "1 BTC"

[chain]
min_dte = 0
max_dte = 90
strike_band = "0.5"

[params]
interval_hours = 1
{params}
"""
VENUES = """
[deribit_option]
name = "DERIBIT"
source = "deribit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "OPTION"
fee_model = { kind = "capped_option", config = { maker_rate = "0.0003", taker_rate = "0.0003", cap_rate = "0.125" } }
"""
# a low at -100 and a high at -50, then a flat level: the IV rank is the share of
# the way up from 30 to 100
LOW_RANK = {-100: 30.0, -50: 100.0, **dict.fromkeys(range(48), 51.0)}
HIGH_RANK = {-100: 30.0, -50: 100.0, **dict.fromkeys(range(48), 90.0)}


def run_strategy(
    tmp_path: Path, catalog: Path, name: str, **params: Any
) -> tuple[ParquetResultStore, str]:
    lines = "\n".join(f"{key} = {value!r}" for key, value in params.items())
    tmp_path.mkdir(parents=True, exist_ok=True)
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC.format(name=name, params=lines.replace("'", '"')))
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog, max_chain_contracts=2_000))
    return store, sink.run_id


def with_dvol(catalog: Path, dvol: dict[int, float]) -> Path:
    write_dvol(catalog, dvol)
    return catalog


def legs_of(store: ParquetResultStore, run_id: str, combo: str) -> pd.DataFrame:
    """The fills of ``combo`` (``C1``), by time, with the tags of their orders."""
    orders = store.load(run_id, "orders").set_index("venue_order_id")["tags"]
    fills = store.load(run_id, "fills").sort_values("ts_event")
    tagged = fills.assign(
        combo=[next(iter(orders[each])) for each in fills["venue_order_id"]]
    )
    return pd.DataFrame(tagged[tagged["combo"] == f"COMBO:{combo}"]).reset_index(
        drop=True
    )
