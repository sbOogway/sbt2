from pathlib import Path

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "run_strategies:BuyUsdThenSell"
instruments = ["BTC-PERPETUAL.DERIBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
bars = "candles"
execution = { marks = "bars", fee_model = { kind = "maker_taker", config = { maker_rate = "0.00015", taker_rate = "0.00035" } } }
capital = "1 BTC"
"""


def run(tmp_path: Path, catalog: Path) -> tuple[ParquetResultStore, str]:
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC)
    [resolved] = load(spec)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog))
    return store, sink.run_id
