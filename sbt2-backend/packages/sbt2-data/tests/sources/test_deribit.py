import asyncio
import json
import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple
from urllib.parse import parse_qs, urlsplit

import pytest
from nautilus_trader.model import (
    AggressorSide,
    Bar,
    CryptoOption,
    GreeksConvention,
    IndexInstrument,
    IndexPriceUpdate,
    InstrumentId,
    MarkPriceUpdate,
    OptionGreeks,
    OptionKind,
    TradeTick,
    black_scholes_greeks,
)
from replay import Replay

from sbt2.data import DayRange
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
BTC_INDEX = InstrumentId.from_str("BTC_USD.DERIBIT")


def fetched(raw: RawFile) -> Any:
    assert callable(raw.origin)
    return json.loads(asyncio.run(raw.origin()))


def saved(raw: RawFile, root: Path) -> Path:
    assert callable(raw.origin)
    path = root / raw.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(asyncio.run(raw.origin()))
    return path


def parsed_of(
    source: Source, data_type: type, root: Path
) -> dict[InstrumentId, list[Any]]:
    snapshot = saved(source.instrument_snapshot("BTC", SNAPSHOT_DAY), root)
    day = saved(source.day_file("BTC", data_type, DAY), root)
    instruments = source.parse_instruments(snapshot)
    ids = source.day_instrument_ids(day, data_type, instruments)
    parsed = source.parse_day(day, data_type, {each: instruments[each] for each in ids})
    return {each: list(records) for each, records in parsed.items()}


def ticks_of(source: Source, root: Path) -> dict[InstrumentId, list[TradeTick]]:
    return parsed_of(source, TradeTick, root)


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
def test_trades_marks_greeks_and_index_prices_are_the_data_types(
    deribit: Source,
) -> None:
    assert deribit.data_types == (
        TradeTick,
        MarkPriceUpdate,
        OptionGreeks,
        IndexPriceUpdate,
    )
    with pytest.raises(UnsupportedDataTypeError):
        deribit.day_file("BTC", Bar, DAY)


@pytest.mark.unit
def test_every_data_type_reads_the_same_raw_day_file(deribit: Source) -> None:
    paths = {deribit.day_file("BTC", each, DAY).path for each in deribit.data_types}

    assert len(paths) == 1


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
        "BTC_USD.DERIBIT",
    }
    assert all(
        isinstance(instruments[each], CryptoOption)
        for each in instruments
        if each != BTC_INDEX
    )


@pytest.mark.unit
def test_the_instrument_snapshot_gives_the_currencys_usd_index(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit
    snapshot = saved(source.instrument_snapshot("BTC", SNAPSHOT_DAY), tmp_path)

    index = source.parse_instruments(snapshot)[BTC_INDEX]

    assert isinstance(index, IndexInstrument)
    assert str(index.quote_currency) == "USD"
    assert index.price_precision == 2
    assert str(index.price_increment) == "0.01"
    assert index.ts_init == 1_791_331_200_000_000_000


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

    instruments = source.parse_instruments(snapshot)
    ids = source.day_instrument_ids(day, TradeTick, instruments)

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
    ids = deribit.day_instrument_ids(
        tmp_path / "nope.json", TradeTick, {PUT_88K: object()}
    )

    assert ids == ()


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
            for each in deribit.day_instrument_ids(day, TradeTick, instruments)
        },
    )

    ((_, (tick,)),) = parsed.items()
    assert tick.aggressor_side == AggressorSide.SELL


@pytest.mark.unit
def test_mark_prices_keep_deribits_decimals(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit

    (lone,) = parsed_of(source, MarkPriceUpdate, tmp_path)[CALL_135K]

    assert lone.value.precision == 8
    assert lone.value.as_double() == 0.00376973


@pytest.mark.unit
def test_a_trade_without_an_iv_gives_no_option_greeks(
    deribit: Source, tmp_path: Path
) -> None:
    spec = json.loads(Path(__file__).with_name("deribit_responses.json").read_text())
    snapshot = tmp_path / "BTC2026-10-07.json"
    snapshot.write_text(json.dumps(spec[4]["response"]["result"]))
    trades = spec[0]["response"]["result"]["trades"][:2]
    day = tmp_path / "BTC2025-01-01.json"
    day.write_text(json.dumps([{**trades[0], "iv": 0.0}, trades[1]]))
    instruments = deribit.parse_instruments(snapshot)
    ids = deribit.day_instrument_ids(day, OptionGreeks, instruments)

    parsed = deribit.parse_day(
        day, OptionGreeks, {each: instruments[each] for each in ids}
    )

    assert {each.value: len(records) for each, records in parsed.items()} == {
        "BTC-31JAN25-135000-C.DERIBIT": 0,
        "BTC-31JAN25-83000-P.DERIBIT": 1,
    }


@pytest.mark.unit
def test_parse_gives_each_trades_mark_price_as_a_mark_price_update_of_its_contract(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit

    marks = parsed_of(source, MarkPriceUpdate, tmp_path)

    assert [str(each.value) for each in marks[PUT_88K]] == ["0.01163879"] * 4
    assert [each.ts_event for each in marks[PUT_88K]] == [
        1_735_689_642_010 * 1_000_000
    ] * 4
    (lone,) = marks[CALL_135K]
    assert lone == MarkPriceUpdate.from_dict(lone.to_dict())
    assert lone.instrument_id == CALL_135K
    assert str(lone.value) == "0.00376973"
    assert (lone.ts_event, lone.ts_init) == (1_735_689_600_017 * 1_000_000,) * 2
    assert sum(len(each) for each in marks.values()) == len(BTC_TRADE_IDS)


@pytest.mark.unit
def test_parse_gives_each_trades_iv_and_index_price_as_option_greeks(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit

    greeks = parsed_of(source, OptionGreeks, tmp_path)

    assert [each.mark_iv for each in greeks[PUT_88K]] == [0.5544] * 4
    assert [each.underlying_price for each in greeks[PUT_88K]] == [93374.45] * 4
    (lone,) = greeks[CALL_135K]
    assert lone.instrument_id == CALL_135K
    assert lone.mark_iv == 0.7119
    assert lone.underlying_price == 93369.56
    assert (lone.ts_event, lone.ts_init) == (1_735_689_600_017 * 1_000_000,) * 2
    assert lone.convention == GreeksConvention.BLACK_SCHOLES
    assert sum(len(each) for each in greeks.values()) == len(BTC_TRADE_IDS)


class GreeksCase(NamedTuple):
    contract: InstrumentId
    is_call: bool
    strike: float
    expiry_ms: int
    trade_ms: int
    iv: float
    index_price: float


@pytest.mark.unit
@pytest.mark.parametrize(
    "case",
    [
        GreeksCase(
            PUT_88K,
            False,
            88000.0,
            1_736_496_000_000,
            1_735_689_642_010,
            0.5544,
            93374.45,
        ),
        GreeksCase(
            CALL_135K,
            True,
            135000.0,
            1_738_310_400_000,
            1_735_689_600_017,
            0.7119,
            93369.56,
        ),
    ],
)
def test_option_greeks_carry_the_black_scholes_greeks_of_the_trades_iv(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path, case: GreeksCase
) -> None:
    source, _ = replayed_deribit
    years = (case.expiry_ms - case.trade_ms) / (365 * 86_400_000)
    expected = black_scholes_greeks(
        case.index_price, 0.0, 0.0, case.iv, case.is_call, case.strike, years
    )

    greeks = parsed_of(source, OptionGreeks, tmp_path)[case.contract][0]

    assert greeks.delta == pytest.approx(expected.delta)
    assert greeks.gamma == pytest.approx(expected.gamma)
    assert greeks.vega == pytest.approx(expected.vega)
    assert greeks.theta == pytest.approx(expected.theta)
    assert (greeks.delta > 0) == case.is_call


@pytest.mark.unit
def test_parse_gives_each_trades_index_price_as_an_index_price_update_of_its_currency(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit

    parsed = parsed_of(source, IndexPriceUpdate, tmp_path)

    (prices,) = parsed.values()
    assert list(parsed) == [BTC_INDEX]
    assert prices[0] == IndexPriceUpdate.from_dict(prices[0].to_dict())
    assert {each.instrument_id for each in prices} == {BTC_INDEX}
    assert [str(each.value) for each in prices][:3] == [
        "93369.56",
        "93366.92",
        "93354.26",
    ]
    stamps = [each.ts_event for each in prices]
    assert stamps == sorted(stamps)
    assert prices[0].ts_event == prices[0].ts_init == 1_735_689_600_017 * 1_000_000
    assert len(prices) == len(BTC_TRADE_IDS)


BTC_DVOL = InstrumentId.from_str("BTC_DVOL.DERIBIT")
DVOL_DAY_FILE = "deribit/dvol/BTC_DVOL/BTC_DVOL2025-01-01.json"


@pytest.mark.unit
def test_dvol_is_a_symbol_of_index_prices(deribit: Source) -> None:
    assert deribit.instrument_id("BTC_DVOL") == BTC_DVOL
    assert deribit.symbol(BTC_DVOL) == "BTC_DVOL"
    assert deribit.day_file("BTC_DVOL", IndexPriceUpdate, DAY).path == PurePosixPath(
        DVOL_DAY_FILE
    )
    with pytest.raises(UnsupportedDataTypeError):
        deribit.day_file("BTC_DVOL", TradeTick, DAY)


@pytest.mark.unit
def test_only_the_index_prices_of_dvol_are_planned(deribit: Source) -> None:
    planned = DayRange(("BTC_DVOL",), DAY, DAY).plan(deribit)

    assert [(symbol, data_type) for symbol, data_type, _ in planned] == [
        ("BTC_DVOL", IndexPriceUpdate)
    ]


@pytest.mark.unit
def test_a_dvol_day_file_holds_the_hourly_dvol_of_the_currency(
    replayed_deribit: tuple[Source, Replay],
) -> None:
    source, served = replayed_deribit

    rows = fetched(source.day_file("BTC_DVOL", IndexPriceUpdate, DAY))

    assert [each[0] for each in rows] == [
        DAY_START_MS + hour * 3_600_000 for hour in range(24)
    ]
    assert rows[0] == [DAY_START_MS, 60.03, 60.35, 60.0, 60.26]
    (target,) = served.requests
    query = parse_qs(urlsplit(target).query)
    assert query["currency"] == ["BTC"]
    assert query["resolution"] == ["3600"]
    assert query["start_timestamp"] == [str(DAY_START_MS)]
    assert query["end_timestamp"] == [str(DAY_END_MS)]


@pytest.mark.unit
def test_dvol_parses_into_index_price_updates_of_the_dvol_index(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit
    snapshot = saved(source.instrument_snapshot("BTC_DVOL", SNAPSHOT_DAY), tmp_path)
    day = saved(source.day_file("BTC_DVOL", IndexPriceUpdate, DAY), tmp_path)
    instruments = source.parse_instruments(snapshot)
    ids = source.day_instrument_ids(day, IndexPriceUpdate, instruments)

    parsed = source.parse_day(
        day, IndexPriceUpdate, {each: instruments[each] for each in ids}
    )

    assert list(parsed) == [BTC_DVOL]
    updates = parsed[BTC_DVOL]
    assert len(updates) == 24
    assert updates[0] == IndexPriceUpdate.from_dict(updates[0].to_dict())
    assert {each.instrument_id for each in updates} == {BTC_DVOL}
    assert [str(each.value) for each in updates][:3] == ["60.03", "60.26", "60.09"]
    assert (
        updates[1].ts_event
        == updates[1].ts_init
        == (DAY_START_MS + 3_600_000) * (1_000_000)
    )
    assert isinstance(instruments[BTC_DVOL], IndexInstrument)


@pytest.mark.unit
def test_dvol_is_the_value_known_at_each_hour(deribit: Source, tmp_path: Path) -> None:
    snapshot = tmp_path / "BTC_DVOL2026-10-07.json"
    snapshot.write_text("{}")
    day = tmp_path / "BTC_DVOL2025-01-01.json"
    day.write_text(json.dumps([[DAY_START_MS, 50.0, 70.0, 40.0, 60.0]]))
    instruments = deribit.parse_instruments(snapshot)

    parsed = deribit.parse_day(day, IndexPriceUpdate, instruments)

    ((update,),) = parsed.values()
    assert str(update.value) == "50.00"
    assert update.ts_event == DAY_START_MS * 1_000_000


@pytest.mark.unit
def test_a_missing_dvol_day_file_holds_no_instrument(
    deribit: Source, tmp_path: Path
) -> None:
    ids = deribit.day_instrument_ids(
        tmp_path / "nope.json", IndexPriceUpdate, {BTC_DVOL: object()}
    )

    assert ids == ()


@pytest.mark.unit
def test_a_day_without_dvol_is_missing_at_source(
    replayed_deribit: tuple[Source, Replay],
) -> None:
    source, _ = replayed_deribit

    with pytest.raises(MissingAtSourceError, match=r"BTC DVOL on 2016-01-01"):
        fetched(source.day_file("BTC_DVOL", IndexPriceUpdate, date(2016, 1, 1)))


BTC_DELIVERY = InstrumentId.from_str("BTC_USD_DELIVERY.DERIBIT")
DELIVERY_DAY_FILE = "deribit/delivery/BTC_USD_DELIVERY/BTC_USD_DELIVERY2025-01-01.json"
EXPIRY_NANOS = (DAY_START_MS + 8 * 3_600_000) * 1_000_000


@pytest.mark.unit
def test_dvol_and_delivery_prices_are_data_types(deribit: Source) -> None:
    assert deribit.instrument_id("ETH_USD_DELIVERY") == InstrumentId.from_str(
        "ETH_USD_DELIVERY.DERIBIT"
    )
    assert deribit.symbol(BTC_DELIVERY) == "BTC_USD_DELIVERY"
    assert deribit.day_file(
        "BTC_USD_DELIVERY", IndexPriceUpdate, DAY
    ).path == PurePosixPath(DELIVERY_DAY_FILE)
    with pytest.raises(UnsupportedDataTypeError):
        deribit.day_file("ETH_DVOL", Bar, DAY)


@pytest.mark.unit
def test_a_delivery_day_file_holds_the_days_delivery_price(
    replayed_deribit: tuple[Source, Replay],
) -> None:
    source, served = replayed_deribit

    records = fetched(source.day_file("BTC_USD_DELIVERY", IndexPriceUpdate, DAY))

    assert records == [{"date": "2025-01-01", "delivery_price": 93539.0}]
    queries = [parse_qs(urlsplit(each).query) for each in served.requests]
    assert {each["index_name"][0] for each in queries} == {"btc_usd"}
    assert {each["count"][0] for each in queries} == {"100"}


@pytest.mark.unit
def test_a_delivery_price_parses_into_an_index_price_update_at_the_expiry(
    replayed_deribit: tuple[Source, Replay], tmp_path: Path
) -> None:
    source, _ = replayed_deribit
    snapshot = saved(
        source.instrument_snapshot("BTC_USD_DELIVERY", SNAPSHOT_DAY), tmp_path
    )
    day = saved(source.day_file("BTC_USD_DELIVERY", IndexPriceUpdate, DAY), tmp_path)
    instruments = source.parse_instruments(snapshot)
    ids = source.day_instrument_ids(day, IndexPriceUpdate, instruments)

    parsed = source.parse_day(
        day, IndexPriceUpdate, {each: instruments[each] for each in ids}
    )

    ((instrument_id, (update,)),) = parsed.items()
    assert instrument_id == BTC_DELIVERY
    assert update == IndexPriceUpdate.from_dict(update.to_dict())
    assert update.instrument_id == BTC_DELIVERY
    assert str(update.value) == "93539.00"
    assert update.ts_event == update.ts_init == EXPIRY_NANOS


@pytest.mark.unit
@pytest.mark.parametrize("missing_day", [date(2016, 1, 1), date(2016, 11, 19)])
def test_a_day_without_a_delivery_price_is_missing_at_source(
    replayed_deribit: tuple[Source, Replay], missing_day: date
) -> None:
    source, _ = replayed_deribit

    with pytest.raises(MissingAtSourceError, match=missing_day.isoformat()):
        fetched(source.day_file("BTC_USD_DELIVERY", IndexPriceUpdate, missing_day))


def _null_trade_files(root: Path, field: str) -> tuple[Path, Path]:
    spec = json.loads(Path(__file__).with_name("deribit_responses.json").read_text())
    snapshot = root / "BTC2026-10-07.json"
    snapshot.write_text(json.dumps(spec[4]["response"]["result"]))
    trades = spec[0]["response"]["result"]["trades"][:2]
    day = root / "BTC2025-01-01.json"
    day.write_text(json.dumps([{**trades[0], field: None}, trades[1]]))
    return snapshot, day


@pytest.mark.unit
def test_a_trade_without_a_mark_price_gives_no_mark_update(
    deribit: Source, tmp_path: Path
) -> None:
    snapshot, day = _null_trade_files(tmp_path, "mark_price")
    instruments = deribit.parse_instruments(snapshot)
    parsed = {
        kind: deribit.parse_day(
            day,
            kind,
            {
                each: instruments[each]
                for each in deribit.day_instrument_ids(day, kind, instruments)
            },
        )
        for kind in (TradeTick, MarkPriceUpdate)
    }

    assert len(parsed[TradeTick][CALL_135K]) == 1
    assert sum(len(records) for records in parsed[TradeTick].values()) == 2
    assert parsed[MarkPriceUpdate][CALL_135K] == []
    assert sum(len(records) for records in parsed[MarkPriceUpdate].values()) == 1


@pytest.mark.unit
def test_a_trade_without_an_index_price_gives_no_greeks_and_no_index_update(
    deribit: Source, tmp_path: Path
) -> None:
    snapshot, day = _null_trade_files(tmp_path, "index_price")
    instruments = deribit.parse_instruments(snapshot)
    parsed = {
        kind: deribit.parse_day(
            day,
            kind,
            {
                each: instruments[each]
                for each in deribit.day_instrument_ids(day, kind, instruments)
            },
        )
        for kind in (TradeTick, OptionGreeks, IndexPriceUpdate)
    }

    assert len(parsed[TradeTick][CALL_135K]) == 1
    assert sum(len(records) for records in parsed[TradeTick].values()) == 2
    assert parsed[OptionGreeks][CALL_135K] == []
    assert sum(len(records) for records in parsed[OptionGreeks].values()) == 1
    [index] = parsed[IndexPriceUpdate][BTC_INDEX]
    assert index.ts_event == 1_735_689_605_718 * 1_000_000
