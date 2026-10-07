import asyncio
import json
import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    CryptoOption,
    InstrumentId,
    OptionKind,
    TradeTick,
)
from replay import Replay

from sbt2.data.sources import (
    MissingAtSourceError,
    RawFile,
    Source,
    UnsupportedDataTypeError,
)

DAY = date(2025, 1, 1)
DAY_START_MS = 1_735_689_600_000
DAY_END_MS = DAY_START_MS + 86_400_000 - 1
SNAPSHOT_DAY = date(2026, 10, 7)
BTC_TRADE_IDS = [
    "338110691",
    "338110702",
    "338110703",
    "338110737",
    "338110741",
    "338110742",
    "338110744",
    "338110745",
]
PUT_88K = InstrumentId.from_str("BTC-10JAN25-88000-P.DERIBIT")
CALL_135K = InstrumentId.from_str("BTC-31JAN25-135000-C.DERIBIT")


def fetched(raw: RawFile) -> Any:
    assert callable(raw.origin)
    return json.loads(asyncio.run(raw.origin()))


def saved(raw: RawFile, root: Path) -> Path:
    assert callable(raw.origin)
    path = root / raw.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(asyncio.run(raw.origin()))
    return path


def ticks_of(source: Source, root: Path) -> dict[InstrumentId, list[TradeTick]]:
    snapshot = saved(source.instrument_snapshot("BTC", SNAPSHOT_DAY), root)
    day = saved(source.day_file("BTC", TradeTick, DAY), root)
    instruments = source.parse_instruments(snapshot)
    ids = source.day_instrument_ids(day, instruments)
    parsed = source.parse_day(day, TradeTick, {each: instruments[each] for each in ids})
    return {each: list(ticks) for each, ticks in parsed.items()}


@pytest.mark.unit
def test_instrument_ids_are_deribit_option_ids(deribit: Source) -> None:
    assert deribit.instrument_id("BTC") == InstrumentId.from_str("BTC-OPTIONS.DERIBIT")


@pytest.mark.unit
def test_only_btc_and_eth_are_symbols(deribit: Source) -> None:
    with pytest.raises(ValueError, match="BTC, ETH"):
        deribit.instrument_id("SOL")


@pytest.mark.unit
@pytest.mark.parametrize(
    "instrument_id", ["BTC-OPTIONS.DERIBIT", "BTC-10JAN25-88000-P.DERIBIT"]
)
def test_the_symbol_of_an_instrument_id_is_its_currency(
    deribit: Source, instrument_id: str
) -> None:
    assert deribit.symbol(InstrumentId.from_str(instrument_id)) == "BTC"


@pytest.mark.unit
def test_an_instrument_id_of_another_venue_has_no_deribit_symbol(
    deribit: Source,
) -> None:
    with pytest.raises(ValueError, match=re.escape("BTCUSDT-PERP.BINANCE")):
        deribit.symbol(InstrumentId.from_str("BTCUSDT-PERP.BINANCE"))


@pytest.mark.unit
def test_trades_are_the_only_data_type(deribit: Source) -> None:
    assert deribit.data_types == (TradeTick,)
    with pytest.raises(UnsupportedDataTypeError):
        deribit.day_file("BTC", Bar, DAY)


@pytest.mark.unit
def test_a_day_is_saved_one_json_file_per_currency(deribit: Source) -> None:
    assert deribit.day_file("BTC", TradeTick, DAY).path == PurePosixPath(
        "deribit/option/BTC/trades/BTC2025-01-01.json"
    )


@pytest.mark.unit
def test_instrument_snapshot_is_saved_under_the_day_it_is_taken(
    deribit: Source,
) -> None:
    assert deribit.instrument_snapshot("ETH", date(2026, 9, 28)).path == (
        PurePosixPath("deribit/option/ETH/instrument/ETH2026-09-28.json")
    )


@pytest.mark.unit
def test_a_day_file_pages_through_every_option_trade_of_the_currency(
    replayed_deribit: tuple[Source, Replay],
) -> None:
    source, served = replayed_deribit

    trades = fetched(source.day_file("BTC", TradeTick, DAY))

    assert [each["trade_id"] for each in trades] == BTC_TRADE_IDS
    queries = [parse_qs(urlsplit(each).query) for each in served.requests]
    assert len(queries) == 3
    assert {each["kind"][0] for each in queries} == {"option"}
    assert {each["currency"][0] for each in queries} == {"BTC"}
    assert {each["end_timestamp"][0] for each in queries} == {str(DAY_END_MS)}
    assert queries[0]["start_timestamp"] == [str(DAY_START_MS)]


@pytest.mark.unit
def test_the_raw_trades_keep_every_field_deribit_sends(
    replayed_deribit: tuple[Source, Replay],
) -> None:
    source, _ = replayed_deribit

    first = fetched(source.day_file("BTC", TradeTick, DAY))[0]

    assert {"iv", "index_price", "mark_price", "tick_direction", "trade_seq"} <= set(
        first
    )


@pytest.mark.unit
def test_a_day_without_trades_is_missing_at_source(
    replayed_deribit: tuple[Source, Replay],
) -> None:
    source, _ = replayed_deribit

    with pytest.raises(MissingAtSourceError, match=r"BTC option trades on 2016-01-01"):
        fetched(source.day_file("BTC", TradeTick, date(2016, 1, 1)))


@pytest.mark.unit
def test_the_instrument_snapshot_lists_live_and_expired_options(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit
    snapshot = saved(source.instrument_snapshot("BTC", SNAPSHOT_DAY), tmp_path)

    instruments = source.parse_instruments(snapshot)

    assert {each.value for each in instruments} == {
        "BTC-25DEC26-35000-C.DERIBIT",
        "BTC-25DEC26-35000-P.DERIBIT",
        "BTC-10JAN25-88000-P.DERIBIT",
        "BTC-31JAN25-135000-C.DERIBIT",
        "BTC-31JAN25-83000-P.DERIBIT",
        "BTC-3JAN25-96000-P.DERIBIT",
    }
    assert all(isinstance(instruments[each], CryptoOption) for each in instruments)


@pytest.mark.unit
def test_an_option_contract_carries_its_strike_expiry_kind_and_currency(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit
    snapshot = saved(source.instrument_snapshot("BTC", SNAPSHOT_DAY), tmp_path)

    contract = source.parse_instruments(snapshot)[PUT_88K]

    assert contract.id == PUT_88K
    assert contract.option_kind == OptionKind.PUT
    assert str(contract.strike_price) == "88000"
    assert contract.expiration_ns == 1_736_496_000_000 * 1_000_000
    assert contract.activation_ns == 1_734_637_920_000 * 1_000_000
    assert str(contract.underlying) == "BTC"
    assert str(contract.quote_currency) == "BTC"
    assert str(contract.settlement_currency) == "BTC"
    assert contract.is_inverse
    assert str(contract.multiplier) == "1"
    assert contract.price_precision == 4
    assert str(contract.price_increment) == "0.0001"
    assert contract.size_precision == 1
    assert str(contract.size_increment) == "0.1"


@pytest.mark.unit
def test_an_instrument_is_initialised_at_the_start_of_its_snapshots_day(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit
    snapshot = saved(source.instrument_snapshot("BTC", SNAPSHOT_DAY), tmp_path)

    contract = source.parse_instruments(snapshot)[PUT_88K]

    assert contract.ts_init == 1_791_331_200_000_000_000


@pytest.mark.unit
def test_a_day_holds_records_of_the_contracts_traded_that_day(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit
    snapshot = saved(source.instrument_snapshot("BTC", SNAPSHOT_DAY), tmp_path)
    day = saved(source.day_file("BTC", TradeTick, DAY), tmp_path)

    ids = source.day_instrument_ids(day, source.parse_instruments(snapshot))

    assert set(ids) == {
        PUT_88K,
        CALL_135K,
        InstrumentId.from_str("BTC-31JAN25-83000-P.DERIBIT"),
        InstrumentId.from_str("BTC-3JAN25-96000-P.DERIBIT"),
    }


@pytest.mark.unit
def test_a_missing_day_file_holds_no_instrument(
    deribit: Source, tmp_path: Path
) -> None:
    assert deribit.day_instrument_ids(tmp_path / "nope.json", {PUT_88K: object()}) == ()


@pytest.mark.unit
def test_parse_splits_the_trades_into_trade_ticks_by_option_contract(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit

    ticks = ticks_of(source, tmp_path)

    assert [str(each.trade_id) for each in ticks[PUT_88K]] == [
        "338110741",
        "338110742",
        "338110744",
        "338110745",
    ]
    first = ticks[PUT_88K][0]
    assert first == TradeTick.from_dict(first.to_dict())
    assert first.instrument_id == PUT_88K
    assert str(first.price) == "0.0120"
    assert str(first.size) == "3.2"
    assert first.aggressor_side == AggressorSide.BUY
    assert first.ts_event == 1_735_689_642_010 * 1_000_000
    assert first.ts_init == first.ts_event
    (lone,) = ticks[CALL_135K]
    assert (str(lone.price), str(lone.size)) == ("0.0040", "0.1")
    assert sum(len(each) for each in ticks.values()) == len(BTC_TRADE_IDS)


@pytest.mark.unit
def test_the_aggressor_side_is_the_direction_of_the_trade(
    deribit: Source, tmp_path: Path
) -> None:
    spec = json.loads(Path(__file__).with_name("deribit_responses.json").read_text())
    snapshot = tmp_path / "BTC2026-10-07.json"
    snapshot.write_text(json.dumps(spec[4]["response"]["result"]))
    trade = {**spec[0]["response"]["result"]["trades"][1], "direction": "sell"}
    day = tmp_path / "BTC2025-01-01.json"
    day.write_text(json.dumps([trade]))
    instruments = deribit.parse_instruments(snapshot)

    parsed = deribit.parse_day(
        day,
        TradeTick,
        {
            each: instruments[each]
            for each in deribit.day_instrument_ids(day, instruments)
        },
    )

    ((_, (tick,)),) = parsed.items()
    assert tick.aggressor_side == AggressorSide.SELL
