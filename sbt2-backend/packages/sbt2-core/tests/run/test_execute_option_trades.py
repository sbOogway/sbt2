from decimal import Decimal
from pathlib import Path

import pytest
from combo_strategies import OpenStrangle
from option_catalog import INDEX_PRICE, build_ladder_catalog

from sbt2.core.results import ParquetResultStore, trade_statistics
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "combo_strategies:TwoTrades"
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


@pytest.fixture(scope="module")
def ladder(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("ladder_catalog")
    build_ladder_catalog(path, mark_step=Decimal("-0.001"))
    return path


def stored(tmp_path: Path, catalog: Path) -> tuple[ParquetResultStore, str]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC)
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog, max_chain_contracts=2_000))
    return store, sink.run_id


@pytest.mark.integration
def test_an_option_run_stores_its_trades_and_their_statistics(
    tmp_path: Path, ladder: Path
) -> None:
    OpenStrangle.clear()

    store, run_id = stored(tmp_path, ladder)

    trades = store.load(run_id, "trades").set_index("trade_id")
    assert list(trades.index) == ["C1", "C2"]
    assert trades.loc["C1", "ts_closed"] > trades.loc["C2", "ts_closed"]
    assert list(trades["index_at_close"]) == [INDEX_PRICE, INDEX_PRICE]
    assert list(trades["pl_usd"]) == pytest.approx(list(trades["pl"] * INDEX_PRICE))
    equity = store.load(run_id, "equity")
    assert trades["pl"].sum() == pytest.approx(
        equity["total_equity"].iloc[-1] - 1.0, abs=1e-6
    )
    run = store.stored_run(run_id).tables
    found = trade_statistics(run.trades, run.margin, run.currency)
    assert found["Occurrences"] == 2
    assert (found["BPR Peak"] or 0.0) > 0
