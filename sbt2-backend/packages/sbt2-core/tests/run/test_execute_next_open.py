from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from candle_catalog import Candle, write_candles, write_marks
from dated_catalog import EXPIRY, build_bars, future, write_delivery
from future_strategies import HoldUsdToExpiry
from nautilus_trader.model import Money
from nautilus_trader.persistence import ParquetDataCatalog
from synthetic_catalog import START, perpetual

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

TAKER = 0.00055
SPEC = """
strategy = "next_open_strategies:{strategy}"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
params = {params}
period = [2024-01-01, 2024-01-04]
split = {{ validation_start = 2024-01-02, test_start = 2024-01-03 }}
part = "train"
bars = "candles"
execution = {{ {fills}fee_model = {{ kind = "maker_taker", config = {{ maker_rate = "0.0002", taker_rate = "{taker}" }} }} }}
capital = "10000 USDT"
"""
FUTURE_SPEC = """
strategy = "future_strategies:HoldUsdToExpiry"
instruments = ["BTC-2JAN24.DERIBIT"]
params = { side = "BUY", usd = 100000 }
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
bars = "candles"
execution = { fee_model = { kind = "maker_taker", config = { maker_rate = "0.00015", taker_rate = "0.00035" } } }
capital = "1 BTC"
"""
SIGNALS = {
    "BUY": [Candle(0, (100, 110, 90, 105)), Candle(1, (120, 130, 115, 125))],
    "SELL": [Candle(0, (100, 110, 90, 95)), Candle(1, (80, 85, 70, 75))],
}
LONG = SIGNALS["BUY"]
BOUNDARY = START + timedelta(minutes=1)
END = START + timedelta(days=1)


def run(tmp_path: Path, candles: list[Candle], spec: str) -> pd.DataFrame:
    """The fills of a run of ``spec`` on a catalog of ``candles``."""
    write_candles(tmp_path / "catalog", perpetual(), candles)
    return execute_fills(tmp_path, spec)


def execute_fills(tmp_path: Path, spec: str) -> pd.DataFrame:
    store, run_id = execute_spec(tmp_path, spec)
    return store.load(run_id, "fills")


def execute_spec(tmp_path: Path, spec: str) -> tuple[ParquetResultStore, str]:
    path = tmp_path / "spec.toml"
    path.write_text(spec)
    [resolved] = load(path)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(tmp_path / "catalog"))
    return store, sink.run_id


def spec(
    strategy: str = "TradeOnClose", params: str = "{}", fills: str | None = None
) -> str:
    setting = "" if fills is None else f'fills = "{fills}", '
    return SPEC.format(strategy=strategy, params=params, fills=setting, taker=TAKER)


def fills_of(frame: pd.DataFrame) -> list[tuple[str, float, pd.Timestamp]]:
    return [
        (str(qty), float(px), ts)
        for qty, px, ts in zip(
            frame["last_qty"], frame["last_px"], frame["ts_event"], strict=True
        )
    ]


def at_minute(minute: int) -> datetime:
    return START + timedelta(minutes=minute)


@pytest.mark.integration
@pytest.mark.parametrize(("side", "next_open"), [("BUY", 120.0), ("SELL", 80.0)])
def test_an_order_on_a_bar_close_fills_at_the_next_open(
    tmp_path: Path, side: str, next_open: float
) -> None:
    fills = run(tmp_path, SIGNALS[side], spec(params=f'{{ side = "{side}" }}'))

    assert fills_of(fills) == [("1.000", next_open, pd.Timestamp(BOUNDARY))]


@pytest.mark.integration
def test_a_clock_alert_after_the_close_fills_at_the_next_open(tmp_path: Path) -> None:
    fills = run(tmp_path, LONG, spec("TradeOnAlert"))

    assert fills_of(fills) == [
        ("1.000", 120.0, pd.Timestamp(BOUNDARY) + pd.Timedelta(1, "ns"))
    ]


@pytest.mark.integration
def test_close_fills_keep_the_signal_bar_close(tmp_path: Path) -> None:
    fills = run(tmp_path, LONG, spec(fills="close"))

    assert fills_of(fills) == [("1.000", 105.0, pd.Timestamp(BOUNDARY))]


@pytest.mark.integration
def test_a_large_order_fills_as_bar_execution_does(tmp_path: Path) -> None:
    fills = run(tmp_path, LONG, spec(params='{ quantity = "50.000" }'))

    assert fills_of(fills) == [
        ("25.000", 120.0, pd.Timestamp(BOUNDARY)),
        ("25.000", 120.1, pd.Timestamp(BOUNDARY)),
    ]


@pytest.mark.integration
def test_the_fee_is_charged_on_the_open_price(tmp_path: Path) -> None:
    fills = run(tmp_path, LONG, spec(params='{ quantity = "2.000" }'))

    [commission] = fills["commission"]
    assert Money.from_str(commission).as_double() == pytest.approx(TAKER * 2 * 120)


@pytest.mark.integration
def test_an_order_before_a_missing_candle_fills_at_the_signal_close(
    tmp_path: Path,
) -> None:
    candles = [LONG[0], Candle(2, (140, 150, 135, 145))]

    fills = run(tmp_path, candles, spec())

    assert fills_of(fills) == [("1.000", 105.0, pd.Timestamp(BOUNDARY))]


@pytest.mark.integration
def test_an_exit_on_the_last_session_bar_fills_at_the_session_end(
    tmp_path: Path,
) -> None:
    candles = [
        *LONG,
        Candle(719, (200, 210, 190, 205)),
        Candle(720, (220, 230, 215, 225)),
    ]

    fills = run(tmp_path, candles, spec(params="{ exit = 720 }"))

    assert fills_of(fills)[1] == ("1.000", 220.0, at_minute(720))


@pytest.mark.integration
def test_an_order_on_the_last_bar_of_the_run_fills_at_its_close(
    tmp_path: Path,
) -> None:
    candles = [*LONG, Candle(1439, (200, 210, 190, 205))]

    fills = run(tmp_path, candles, spec(params="{ exit = 1440 }"))

    assert fills_of(fills)[1] == ("1.000", 205.0, END)


@pytest.mark.integration
def test_equity_is_still_valued_at_the_marks(tmp_path: Path) -> None:
    candles = [
        Candle(minute, (100 + minute, 101 + minute, 99 + minute, 100.5 + minute))
        for minute in range(62)
    ]
    write_candles(tmp_path / "catalog", perpetual(), candles)
    write_marks(tmp_path / "catalog", perpetual(), candles)

    store, run_id = execute_spec(tmp_path, spec())

    equity = store.load(run_id, "equity").set_index("ts_event")["total_equity"]
    entry, mark, next_open = 101.0, 160.5, 161.0
    sampled = equity[at_minute(61)]
    assert sampled == pytest.approx(10_000 - TAKER * entry + mark - entry, abs=1e-6)
    assert sampled != pytest.approx(10_000 - TAKER * entry + next_open - entry)


@pytest.mark.integration
def test_a_future_held_through_expiry_still_closes_at_delivery(
    tmp_path: Path,
) -> None:
    HoldUsdToExpiry.settled.clear()
    contract = future()
    build_bars(tmp_path / "catalog", contract)
    write_delivery(tmp_path / "catalog", "BTC", {EXPIRY: 55_555.3})
    after = Candle(minutes_to(EXPIRY), (60_000, 60_000, 60_000, 60_000), 1e9)
    ParquetDataCatalog(str(tmp_path / "catalog")).write_bars([after.bar(contract)])

    store, run_id = execute_spec(tmp_path, FUTURE_SPEC)

    fills = store.load(run_id, "fills")
    assert [float(each) for each in fills["last_px"]] == [50_300.0, 55_555.5]
    orders = store.load(run_id, "orders")
    assert list(orders.loc[orders["tags"].notna(), "tags"].map(list)) == [
        ["SETTLEMENT"]
    ]
    assert HoldUsdToExpiry.settled == [(str(contract.id), 55_555.5, 100_000.0)]


def minutes_to(moment: datetime) -> int:
    return int((moment - START).total_seconds()) // 60
