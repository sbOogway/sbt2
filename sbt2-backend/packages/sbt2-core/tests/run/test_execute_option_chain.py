from datetime import UTC, datetime, timedelta
from itertools import pairwise
from math import erf, log, sqrt
from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model import InstrumentId, Money
from option_catalog import (
    EXPIRY_HOUR,
    MARK_IV,
    START,
    build_chain_catalog,
    chain_contract_id,
    mark_at,
)
from run_strategies import (
    ActOnSchedule,
    FilterChain,
    GreekChain,
    ListAliveContracts,
    QuoteChain,
)

from sbt2.core.results import ParquetResultStore
from sbt2.core.run import ChainTooLargeError, RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "run_strategies:ActOnSchedule"
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


DELIVERY_FEE = 0.00015
BALANCE = 1.0
PUT_VALUE = 0.125
SHORT_PUT_MARGIN = 0.15
PUTS = [
    ("2JAN24", 40000),
    ("2JAN24", 45000),
    ("2JAN24", 50000),
    ("12JAN24", 45000),
    ("15FEB24", 45000),
]


def ids(label: str, *strikes: int) -> set[InstrumentId]:
    return {chain_contract_id(label, each, kind) for each in strikes for kind in "CP"}


def names(found: set[InstrumentId]) -> list[str]:
    return sorted(str(each) for each in found)


@pytest.fixture(scope="module")
def catalog(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("chain_catalog")
    build_chain_catalog(path)
    return path


def run(
    tmp_path: Path, catalog: Path, strategy: str, limit: int = 2_000
) -> tuple[ParquetResultStore, str]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(SPEC.replace("run_strategies:ActOnSchedule", strategy))
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog, max_chain_contracts=limit))
    return store, sink.run_id


@pytest.mark.integration
def test_a_chain_strategy_acts_on_its_schedule_without_bars(
    tmp_path: Path, catalog: Path
) -> None:
    ActOnSchedule.ticks.clear()

    run(tmp_path, catalog, "run_strategies:ActOnSchedule")

    ticks = ActOnSchedule.ticks
    assert ticks[0] == datetime(2024, 1, 1, 3, tzinfo=UTC)
    assert {later - earlier for earlier, later in pairwise(ticks)} == {
        timedelta(hours=1)
    }
    assert ticks[-1] >= datetime(2024, 1, 2, 22, tzinfo=UTC)


@pytest.mark.integration
def test_a_chain_strategy_sees_the_contracts_alive_now(
    tmp_path: Path, catalog: Path
) -> None:
    ListAliveContracts.alive.clear()

    run(tmp_path, catalog, "run_strategies:ListAliveContracts")

    alive = ListAliveContracts.alive
    before = alive[datetime(2024, 1, 2, 7, tzinfo=UTC)]
    after = alive[datetime(2024, 1, 2, 8, tzinfo=UTC)]
    assert before == names(
        ids("2JAN24", 40000, 45000, 50000)
        | ids("12JAN24", 45000)
        | ids("15FEB24", 45000)
    )
    assert after == names(ids("12JAN24", 45000) | ids("15FEB24", 45000))


@pytest.mark.integration
def test_a_chain_strategy_filters_the_chain_by_dte_strike_and_kind(
    tmp_path: Path, catalog: Path
) -> None:
    FilterChain.found.clear()
    FilterChain.expiries.clear()

    run(tmp_path, catalog, "run_strategies:FilterChain")

    found = FilterChain.found
    assert found["puts"] == names(
        {chain_contract_id(label, strike, "P") for label, strike in PUTS}
    )
    assert found["far"] == names(ids("15FEB24", 45000))
    assert found["at the money"] == names(
        ids("2JAN24", 45000) | ids("12JAN24", 45000) | ids("15FEB24", 45000)
    )
    assert found["one expiry"] == names(ids("12JAN24", 45000))
    assert found["all of them"] == names(
        {chain_contract_id("2JAN24", strike, "C") for strike in (45000, 50000)}
    )
    assert FilterChain.expiries == [
        datetime(2024, 1, 2, 8, tzinfo=UTC),
        datetime(2024, 1, 12, 8, tzinfo=UTC),
        datetime(2024, 2, 15, 8, tzinfo=UTC),
    ]


@pytest.mark.integration
def test_a_chain_strategy_reads_the_current_quote_of_a_contract(
    tmp_path: Path, catalog: Path
) -> None:
    QuoteChain.quotes.clear()
    tick = datetime(2024, 1, 1, 10, tzinfo=UTC)

    run(tmp_path, catalog, "run_strategies:QuoteChain")

    quotes = QuoteChain.quotes[tick]
    assert sorted(quotes) == names(
        ids("2JAN24", 40000, 45000, 50000)
        | ids("12JAN24", 45000)
        | ids("15FEB24", 45000)
    )
    bid, ask, ts_event = quotes[str(chain_contract_id("15FEB24", 45000, "C"))]
    assert bid < (bid + ask) / 2 < ask
    assert (bid + ask) / 2 == pytest.approx(float(mark_at(10)), rel=0.1)
    assert 0 <= pd.Timestamp(tick).value - ts_event <= 120 * 10**9


def last_mark_hour(ts: int) -> int:
    seconds = (ts - pd.Timestamp(START).value) // 10**9
    return min(seconds // 3600, EXPIRY_HOUR - 1)


@pytest.mark.integration
def test_a_chain_strategy_trades_a_contract_it_picked_and_it_settles_at_expiry(
    tmp_path: Path, catalog: Path
) -> None:
    store, run_id = run(tmp_path, catalog, "run_strategies:SellChainPut")

    [entry, settlement] = store.load(run_id, "fills").to_dict("records")
    put = str(chain_contract_id("2JAN24", 45000, "P"))
    assert (entry["instrument_id"], entry["order_side"]) == (put, "SELL")
    assert (settlement["instrument_id"], settlement["order_side"]) == (put, "BUY")
    assert float(settlement["last_px"]) == pytest.approx(PUT_VALUE)
    equity = store.load(run_id, "equity")["total_equity"].iloc[-1]
    assert equity == pytest.approx(
        BALANCE
        - Money.from_str(str(entry["commission"])).as_double()
        + float(entry["last_px"])
        - PUT_VALUE
        - DELIVERY_FEE
    )
    margin = store.load(run_id, "margin")
    held = [row for row in margin.to_dict("records") if row["margin_used"] > 0]
    assert len(held) > 1
    for row in held:
        mark = float(mark_at(last_mark_hour(pd.Timestamp(row["ts_event"]).value)))
        assert row["margin_used"] == pytest.approx(SHORT_PUT_MARGIN + mark)
    assert margin["margin_used"].iloc[-1] == 0


@pytest.mark.integration
def test_a_chain_run_with_more_contracts_than_the_limit_is_refused_before_it_starts(
    tmp_path: Path, catalog: Path
) -> None:
    with pytest.raises(ChainTooLargeError, match=r"10 contracts.*limit of 5.*narrow"):
        run(tmp_path, catalog, "run_strategies:ActOnSchedule", limit=5)


def call_delta(index: float, hours_left: float) -> float:
    years = hours_left / 24 / 365
    spread = MARK_IV * sqrt(years)
    d1 = (log(index / 45000) + 0.5 * MARK_IV**2 * years) / spread
    return (1 + erf(d1 / sqrt(2))) / 2


@pytest.mark.integration
def test_a_chain_strategy_reads_the_iv_and_greeks_of_a_contract(
    tmp_path: Path,
) -> None:
    GreekChain.seen.clear()
    path = tmp_path / "moving_index"
    prices = [44_000.0 + 100 * hour for hour in range(48)]
    build_chain_catalog(path, index_prices=prices)

    run(tmp_path, path, "run_strategies:GreekChain")

    seen = GreekChain.seen
    assert len(seen) > 40
    for tick, (iv, delta) in seen.items():
        hour = int((tick - START).total_seconds() // 3600)
        hours_left = (
            datetime(2024, 2, 15, 8, tzinfo=UTC) - tick
        ).total_seconds() / 3600
        assert iv == MARK_IV
        assert delta == pytest.approx(
            call_delta(prices[min(hour, 47)], hours_left), abs=1e-5
        )
