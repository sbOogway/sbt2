from pathlib import Path

import pandas as pd
import pytest
from dated_catalog import build_bars, spot
from nautilus_trader.model import Money
from spot_strategies import BuyThenSellCoins

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

CAPITAL = 100_000.0
TAKER = 0.0005
COINS = 0.5
ENTRY = 50_200.0
EXIT = 52_200.0
TOLERANCE = 1e-6


def spec(buy: str, sell: str) -> str:
    return f"""
strategy = "spot_strategies:BuyThenSellCoins"
instruments = ["BTC_USDC.DERIBIT"]
params = {{ buy = "{buy}", sell = "{sell}" }}
period = [2024-01-01T02:00:00, 2024-01-05]
split = {{ validation_start = 2024-01-02, test_start = 2024-01-04 }}
part = "train"
bars = "candles"
execution = {{ fee_model = {{ kind = "maker_taker", config = {{ maker_rate = "0.0002", taker_rate = "{TAKER}" }} }} }}
capital = "{CAPITAL:.0f} USDC"
"""


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("catalog")
    build_bars(path, spot())
    return path


def run(
    tmp_path: Path, catalog: Path, orders: tuple[str, str]
) -> tuple[ParquetResultStore, str]:
    path = tmp_path / "spec.toml"
    path.write_text(spec(*orders))
    [resolved] = load(path)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog))
    return store, sink.run_id


def balances(store: ParquetResultStore, run_id: str, currency: str) -> pd.Series:
    table = store.load(run_id, "balances")
    rows = table.loc[table["currency"] == currency]
    return pd.Series(rows["total_equity"].to_numpy(), index=rows["ts_event"])


def fee(price: float) -> float:
    return COINS * price * TAKER


@pytest.mark.integration
def test_spot_trade_settles_cash_and_holds_the_coin(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog, ("0.500", "0.500"))

    fills = store.load(run_id, "fills")
    assert [float(each) for each in fills["last_px"]] == [ENTRY, EXIT]
    assert [Money.from_str(str(each)).as_double() for each in fills["commission"]] == (
        pytest.approx([fee(ENTRY), fee(EXIT)], abs=TOLERANCE)
    )
    cash, coins = balances(store, run_id, "USDC"), balances(store, run_id, "BTC")
    held = coins.loc[coins > 0].index
    assert len(held) > 0
    assert (coins[held] == COINS).all()
    remaining = CAPITAL - COINS * ENTRY - fee(ENTRY)
    assert list(cash[held]) == pytest.approx([remaining] * len(held), abs=TOLERANCE)
    assert cash.iloc[-1] == pytest.approx(
        CAPITAL + COINS * (EXIT - ENTRY) - fee(ENTRY) - fee(EXIT), abs=TOLERANCE
    )
    assert coins.iloc[-1] == 0


@pytest.mark.integration
def test_spot_cannot_borrow_cash_or_base(tmp_path: Path, catalog: Path) -> None:
    BuyThenSellCoins.refused.clear()

    store, run_id = run(tmp_path, catalog, ("5.000", "1.000"))

    assert [each.split(":")[0] for each in BuyThenSellCoins.refused] == [
        "NOTIONAL_EXCEEDS_FREE_BALANCE",
        "CUMULATIVE_NOTIONAL_EXCEEDS_FREE_BALANCE",
    ]
    assert store.load(run_id, "fills").empty
    assert set(balances(store, run_id, "USDC")) == {CAPITAL}
    assert balances(store, run_id, "BTC").empty
