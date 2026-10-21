from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest
from dated_catalog import (
    EXPIRY,
    build_bars,
    future,
    perpetual,
    write_delivery,
)
from future_strategies import HoldUsdToExpiry, OverReach
from nautilus_trader.model import Money

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

USD = 100_000
MAKER = 0.00015
TAKER = 0.00035
DELIVERY_FEE = 0.00025
# 55,555.3 to the 0.5 tick of the future
DELIVERY = 55_555.5
TOLERANCE = 2e-8


@dataclass(frozen=True)
class Case:
    instrument: str
    strategy: str
    side: str = "BUY"
    usd: int = USD
    validation_start: str = "2024-01-03"

    def spec(self) -> str:
        coin = self.instrument.split("-")[0]
        return f"""
strategy = "future_strategies:{self.strategy}"
instruments = ["{self.instrument}"]
params = {{ side = "{self.side}", usd = {self.usd} }}
period = [2024-01-01T02:00:00, 2024-01-05]
split = {{ validation_start = {self.validation_start}, test_start = 2024-01-04 }}
part = "train"
bars = "candles"
execution = {{ fee_model = {{ kind = "maker_taker", config = {{ maker_rate = "{MAKER}", taker_rate = "{TAKER}" }} }} }}
capital = "1 {coin}"
"""


@dataclass(frozen=True)
class Trade:
    """What ``TradeUsd`` does on one side: its fill prices and fee rates, and the
    mark at a time of the equity while its position is open."""

    sign: int
    entry: tuple[float, float]
    exit: tuple[float, float]
    marked: tuple[str, float]


# The equity is sampled every hour from the first fill on: the short opens at
# the close of the first minute of hour 7. The times are in UTC.
TRADES = {
    "BUY": Trade(1, (50_200, TAKER), (50_700, MAKER), ("2024-01-01 05:00", 50_400)),
    "SELL": Trade(
        -1, (50_700, MAKER), (52_200, TAKER), ("2024-01-01 10:00:59.999999999", 51_000)
    ),
}


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Both coins' futures and perpetuals, and the delivery prices of the futures."""
    path = tmp_path_factory.mktemp("catalog")
    for coin in ("BTC", "ETH"):
        build_bars(path, future(coin))
        build_bars(path, perpetual(coin))
        write_delivery(path, coin, {EXPIRY: 55_555.3})
    return path


def run(tmp_path: Path, catalog: Path, case: Case) -> tuple[ParquetResultStore, str]:
    spec = tmp_path / f"{case.strategy}-{case.instrument}.toml"
    spec.write_text(case.spec())
    [resolved] = load(spec)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog))
    return store, sink.run_id


def amounts(frame: pd.DataFrame, column: str) -> list[float]:
    return [Money.from_str(str(each)).as_double() for each in frame[column]]


def fee(price: float, rate: float, usd: int = USD) -> float:
    return usd / price * rate


def gain(sign: int, entry: float, exit: float, usd: int = USD) -> float:
    return sign * usd * (1 / entry - 1 / exit)


@pytest.mark.integration
@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("coin", ["BTC", "ETH"])
def test_future_trade_pnl_and_fees(
    tmp_path: Path, catalog: Path, coin: str, side: str
) -> None:
    case = Case(
        f"{coin}-2JAN24.DERIBIT", "TradeUsd", side, validation_start="2024-01-02"
    )
    trade = TRADES[side]

    store, run_id = run(tmp_path, catalog, case)

    fills = store.load(run_id, "fills")
    (entry, entry_rate), (exit, exit_rate) = trade.entry, trade.exit
    assert [float(each) for each in fills["last_px"]] == [entry, exit]
    assert amounts(fills, "commission") == pytest.approx(
        [fee(entry, entry_rate), fee(exit, exit_rate)], abs=1e-8
    )
    realized = (
        gain(trade.sign, entry, exit) - fee(entry, entry_rate) - fee(exit, exit_rate)
    )
    positions = store.load(run_id, "positions")
    assert Money.from_str(positions["realized_pnl"].iloc[0]).currency.code == coin
    assert amounts(positions, "realized_pnl") == pytest.approx(
        [realized], abs=TOLERANCE
    )
    equity = store.load(run_id, "equity").set_index("ts_event")["total_equity"]
    moment, mark = trade.marked
    assert equity[moment] == pytest.approx(
        1 - fee(entry, entry_rate) + gain(trade.sign, entry, mark), abs=TOLERANCE
    )
    assert equity.iloc[-1] == pytest.approx(1 + realized, abs=TOLERANCE)
    assert store.load(run_id, "carry").empty


def margins(store: ParquetResultStore, run_id: str) -> list[tuple[str, str]]:
    """The initial and maintenance margin of each account state up to the expiry."""
    account = store.load(run_id, "account")
    before = account.loc[account.index < EXPIRY - timedelta(hours=1)]
    return [
        (each["initial"], each["maintenance"])
        for states in before["margins"]
        for each in states
    ]


@pytest.mark.integration
@pytest.mark.parametrize("coin", ["BTC", "ETH"])
def test_future_margin_matches_perpetual(
    tmp_path: Path, catalog: Path, coin: str
) -> None:
    OverReach.refused.clear()
    (tmp_path / "future").mkdir()
    (tmp_path / "perpetual").mkdir()
    dated = run(
        tmp_path / "future", catalog, Case(f"{coin}-2JAN24.DERIBIT", "OverReach")
    )
    perpetual_refusals = list(OverReach.refused)
    OverReach.refused.clear()
    perpetual = run(
        tmp_path / "perpetual", catalog, Case(f"{coin}-PERPETUAL.DERIBIT", "OverReach")
    )

    assert margins(*dated) == margins(*perpetual)
    assert ("0.00199203", "0.00264940") in margins(*dated)
    assert perpetual_refusals == OverReach.refused
    [refusal] = OverReach.refused
    assert refusal.startswith("INITIAL_MARGIN_EXCEEDS_FREE_BALANCE")


@pytest.mark.integration
@pytest.mark.parametrize("side", ["BUY", "SELL"])
@pytest.mark.parametrize("coin", ["BTC", "ETH"])
def test_future_expiry_closes_at_delivery(
    tmp_path: Path, catalog: Path, coin: str, side: str
) -> None:
    HoldUsdToExpiry.settled.clear()
    instrument = f"{coin}-2JAN24.DERIBIT"

    store, run_id = run(tmp_path, catalog, Case(instrument, "HoldUsdToExpiry", side))

    [entry, settlement] = store.load(run_id, "fills").to_dict("records")
    assert float(settlement["last_px"]) == DELIVERY
    assert amounts(pd.DataFrame([settlement]), "commission") == pytest.approx(
        [fee(DELIVERY, DELIVERY_FEE)], abs=1e-8
    )
    orders = store.load(run_id, "orders")
    assert sorted(orders["status"]) == ["CANCELED", "FILLED", "FILLED"]
    assert list(orders.loc[orders["tags"].notna(), "tags"].map(list)) == [
        ["SETTLEMENT"]
    ]
    [position] = store.load(run_id, "positions").to_dict("records")
    assert position["side"] == "FLAT"
    sign = TRADES[side].sign
    entry_px = float(entry["last_px"])
    equity = store.load(run_id, "equity")["total_equity"].iloc[-1]
    assert equity == pytest.approx(
        1
        - fee(entry_px, TAKER)
        + gain(sign, entry_px, DELIVERY)
        - fee(DELIVERY, DELIVERY_FEE),
        abs=TOLERANCE,
    )
    assert HoldUsdToExpiry.settled == [(instrument, DELIVERY, float(USD))]
