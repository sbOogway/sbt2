from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from deribit_perpetual_catalog import (
    FUNDING_RATE,
    build_catalog,
    perpetual,
    price_in_hour,
)
from deribit_perpetual_runs import SPEC, run
from nautilus_trader.model import Bar, FundingRateUpdate, Money
from nautilus_trader.persistence import ParquetDataCatalog
from synthetic_catalog import START

from sbt2.core.assets import NoMarksError
from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

CONTRACTS = 100_000
OPEN_HOUR = 3
CLOSE_HOUR = 23
TAKER_RATE = 0.00035
TOLERANCE = 2e-8


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("catalog")
    build_catalog(path)
    return path


def amounts(frame: pd.DataFrame, column: str) -> list[float]:
    return [Money.from_str(each).as_double() for each in frame[column]]


def at_hour(hour: int) -> datetime:
    return START + timedelta(hours=hour)


def last_price_before(hour: int) -> float:
    """The close of the last bar before the hour starts."""
    return float(price_in_hour(hour - 1))


def fee(price: float) -> float:
    return CONTRACTS / price * TAKER_RATE


@pytest.mark.integration
def test_a_run_on_the_deribit_perpetual_values_its_position_at_the_bar_close(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog)

    equity = store.load(run_id, "equity").set_index("ts_event")["total_equity"]
    carry = store.load(run_id, "carry")
    paid = sum(
        amount
        for ts, amount in zip(
            carry["ts_event"], amounts(carry, "pnl_change"), strict=True
        )
        if ts < at_hour(10)
    )
    open_price, mark = last_price_before(OPEN_HOUR), last_price_before(10)
    open_gain = CONTRACTS * (1 / open_price - 1 / mark)
    assert equity[at_hour(10)] == pytest.approx(
        1 - fee(open_price) + paid + open_gain, abs=TOLERANCE
    )


@pytest.mark.integration
def test_a_run_on_the_deribit_perpetual_pays_the_hourly_funding(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog)

    carry = store.load(run_id, "carry")
    hours = [(each - at_hour(0)).total_seconds() / 3600 for each in carry["ts_event"]]
    assert hours == list(range(OPEN_HOUR, CLOSE_HOUR))
    expected = [
        -float(FUNDING_RATE) * CONTRACTS / last_price_before(int(hour))
        for hour in hours
    ]
    assert amounts(carry, "pnl_change") == pytest.approx(expected, abs=TOLERANCE)
    [summary] = store.runs().to_dict("records")
    assert summary["total_carry"] == pytest.approx(sum(expected), abs=1e-7)


@pytest.mark.integration
def test_the_pl_of_an_inverse_perpetual_is_in_the_coin(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog)

    open_price, close_price = (
        last_price_before(OPEN_HOUR),
        last_price_before(CLOSE_HOUR),
    )
    gain = CONTRACTS * (1 / open_price - 1 / close_price)
    fees = fee(open_price) + fee(close_price)
    positions = store.load(run_id, "positions")
    assert Money.from_str(positions["realized_pnl"].iloc[0]).currency.code == "BTC"
    carry = store.load(run_id, "carry")
    funding = sum(amounts(carry, "pnl_change"))
    assert amounts(positions, "realized_pnl") == pytest.approx(
        [gain - fees + funding], abs=TOLERANCE
    )
    equity = store.load(run_id, "equity")["total_equity"]
    assert equity.iloc[-1] == pytest.approx(1 + gain - fees + funding, abs=TOLERANCE)


@pytest.mark.unit
def test_marks_from_bars_stream_bars_and_funding_but_no_mark_prices(
    tmp_path: Path,
) -> None:
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC)

    [resolved] = load(spec)

    assert set(resolved.data_types) == {Bar, FundingRateUpdate}


@pytest.mark.integration
def test_a_run_without_bars_cannot_make_the_marks(tmp_path: Path) -> None:
    empty = tmp_path / "catalog"
    empty.mkdir()
    ParquetDataCatalog(str(empty)).write_instruments([perpetual()])
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC)
    [resolved] = load(spec)
    sink = ParquetResultStore(tmp_path / "results").new_run(resolved)

    with pytest.raises(NoMarksError, match="1-minute bars"):
        execute(resolved, sink, RunSettings(empty))
