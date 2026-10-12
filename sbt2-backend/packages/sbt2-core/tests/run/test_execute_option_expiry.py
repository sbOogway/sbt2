from pathlib import Path

import pytest
from nautilus_trader.model import InstrumentId, Money
from option_catalog import EXPIRING_CALL, EXPIRING_PUT, build_expiring_catalog

from sbt2.core.assets import NoDeliveryPriceError
from sbt2.core.results import ParquetResultStore
from sbt2.core.run import RunSettings, execute
from sbt2.core.spec import load

SPEC = """
strategy = "run_strategies:BuyOneOption"
instruments = ["BTC-2JAN24-50000-C.DERIBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
venue = "deribit_option"
capital = "1 BTC"
"""
VENUES = """
[deribit_option]
name = "DERIBIT"
source = "deribit"
asset_class = "CRYPTOCURRENCY"
instrument_class = "OPTION"
fee_model = { kind = "capped_option", config = { maker_rate = "0.0003", taker_rate = "0.0003", cap_rate = "0.125" } }
"""
BASE_FEE = 0.0003
DELIVERY_FEE = 0.00015
BALANCE = 1.0
IN_THE_MONEY = 62_500.0
LOW_DELIVERY = 40_000.0
# (62,500 - 50,000) / 62,500 and (50,000 - 40,000) / 40,000: whole numbers of ticks
CALL_VALUE = 0.2
PUT_VALUE = 0.25


@pytest.fixture(scope="module")
def in_the_money(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("in_the_money")
    build_expiring_catalog(path, IN_THE_MONEY)
    return path


@pytest.fixture(scope="module")
def low_delivery(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("low_delivery")
    build_expiring_catalog(path, LOW_DELIVERY)
    return path


def run(
    tmp_path: Path, catalog: Path, instrument: InstrumentId, strategy: str
) -> tuple[ParquetResultStore, str]:
    spec, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    spec.write_text(
        SPEC.replace("run_strategies:BuyOneOption", strategy).replace(
            "BTC-2JAN24-50000-C.DERIBIT", str(instrument)
        )
    )
    venues.write_text(VENUES)
    [resolved] = load(spec, venues)
    store = ParquetResultStore(tmp_path / "results")
    sink = store.new_run(resolved)
    execute(resolved, sink, RunSettings(catalog))
    return store, sink.run_id


def commission(fill: dict[str, object]) -> float:
    return Money.from_str(str(fill["commission"])).as_double()


@pytest.mark.integration
def test_a_long_call_held_to_expiry_settles_at_its_value(
    tmp_path: Path, in_the_money: Path
) -> None:
    store, run_id = run(
        tmp_path, in_the_money, EXPIRING_CALL, "run_strategies:BuyOneOption"
    )

    [entry, settlement] = store.load(run_id, "fills").to_dict("records")
    assert float(settlement["last_px"]) == pytest.approx(CALL_VALUE)
    assert commission(settlement) == pytest.approx(DELIVERY_FEE)
    [position] = store.load(run_id, "positions").to_dict("records")
    assert position["side"] == "FLAT"
    equity = store.load(run_id, "equity")["total_equity"].iloc[-1]
    assert equity == pytest.approx(
        BALANCE
        - commission(entry)
        - float(entry["last_px"])
        + CALL_VALUE
        - DELIVERY_FEE
    )


@pytest.mark.integration
def test_a_short_put_held_to_expiry_pays_its_value(
    tmp_path: Path, low_delivery: Path
) -> None:
    store, run_id = run(
        tmp_path, low_delivery, EXPIRING_PUT, "run_strategies:SellOneOption"
    )

    [entry, settlement] = store.load(run_id, "fills").to_dict("records")
    assert settlement["order_side"] == "BUY"
    assert float(settlement["last_px"]) == pytest.approx(PUT_VALUE)
    equity = store.load(run_id, "equity")["total_equity"].iloc[-1]
    assert equity == pytest.approx(
        BALANCE - commission(entry) + float(entry["last_px"]) - PUT_VALUE - DELIVERY_FEE
    )


@pytest.mark.integration
def test_a_worthless_option_expires_without_a_delivery_fee(
    tmp_path: Path, low_delivery: Path
) -> None:
    store, run_id = run(
        tmp_path, low_delivery, EXPIRING_CALL, "run_strategies:BuyOneOption"
    )

    [entry, settlement] = store.load(run_id, "fills").to_dict("records")
    assert float(settlement["last_px"]) == 0
    assert commission(settlement) == 0
    equity = store.load(run_id, "equity")["total_equity"].iloc[-1]
    assert equity == pytest.approx(
        BALANCE - commission(entry) - float(entry["last_px"])
    )


@pytest.mark.integration
def test_a_run_with_an_expiry_but_no_delivery_price_names_the_missing_day(
    tmp_path: Path,
) -> None:
    bare = tmp_path / "bare_catalog"
    build_expiring_catalog(bare, None)

    with pytest.raises(NoDeliveryPriceError, match="2024-01-02"):
        run(tmp_path, bare, EXPIRING_CALL, "run_strategies:BuyOneOption")
