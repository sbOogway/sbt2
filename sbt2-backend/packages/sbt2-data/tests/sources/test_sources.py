from datetime import date
from pathlib import Path

import pytest
from nautilus_trader.model import (
    AssetClass,
    Bar,
    InstrumentClass,
    InstrumentId,
    TradeTick,
)

from sbt2.data.sources import (
    Gap,
    ListedGap,
    Source,
    UnknownSourceError,
    UnsupportedDataTypeError,
    add_known_gaps,
    known_gaps,
    listed_gaps,
    remove_known_gaps,
    source,
    source_for,
    source_name,
)
from sbt2.data.sources.binance import BinanceSource
from sbt2.data.sources.coinbase_intx import CoinbaseIntxSource
from sbt2.data.sources.deribit import DeribitSource
from sbt2.data.sources.okx import OkxSource


@pytest.mark.unit
def test_a_missing_known_gaps_file_means_none(tmp_path: Path) -> None:
    file = tmp_path / "known_gaps.toml"

    assert source("bybit", file).known_gaps == frozenset()
    assert known_gaps(file) == frozenset()


@pytest.mark.unit
def test_known_gaps_come_from_the_data_roots_file(tmp_path: Path) -> None:
    file = tmp_path / "known_gaps.toml"
    file.write_text(
        'bybit = [{ symbol = "BTCUSDT", data = "trades", day = 2020-03-25 }]\n'
    )

    assert source("bybit", file).known_gaps == {
        Gap(InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT"), TradeTick, date(2020, 3, 25))
    }


@pytest.mark.unit
def test_known_gaps_can_name_candles(tmp_path: Path) -> None:
    file = tmp_path / "known_gaps.toml"
    file.write_text(
        'bybit = [{ symbol = "BTCUSDT", data = "candles", day = 2020-03-25 }]\n'
    )

    assert source("bybit", file).known_gaps == {
        Gap(InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT"), Bar, date(2020, 3, 25))
    }


@pytest.mark.unit
def test_unknown_source_is_refused(tmp_path: Path) -> None:
    with pytest.raises(
        UnknownSourceError, match="known: binance, bybit, coinbase_intx, deribit, okx"
    ):
        source("nope", tmp_path / "known_gaps.toml")


@pytest.mark.unit
def test_deribit_is_a_listed_source(tmp_path: Path) -> None:
    assert isinstance(source("deribit", tmp_path / "known_gaps.toml"), DeribitSource)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("name", "kind", "symbol", "instrument_id"),
    [
        ("binance", BinanceSource, "BTCUSDT", "BTCUSDT-PERP.BINANCE"),
        ("okx", OkxSource, "ETH-USDT-SWAP", "ETH-USDT-SWAP.OKX"),
        ("coinbase_intx", CoinbaseIntxSource, "BTC-PERP", "BTC-PERP.COINBASE_INTX"),
    ],
)
def test_the_new_sources_are_listed(
    tmp_path: Path, name: str, kind: type[Source], symbol: str, instrument_id: str
) -> None:
    file = tmp_path / "known_gaps.toml"
    file.write_text(
        f'{name} = [{{ symbol = "{symbol}", data = "candles", day = 2023-09-01 }}]\n'
    )

    listed = source(name, file)

    assert isinstance(listed, kind)
    assert listed.known_gaps == {
        Gap(InstrumentId.from_str(instrument_id), Bar, date(2023, 9, 1))
    }


@pytest.mark.unit
def test_deribit_known_gaps_name_a_currency_and_its_trades(tmp_path: Path) -> None:
    file = tmp_path / "known_gaps.toml"
    file.write_text(
        'deribit = [{ symbol = "BTC", data = "trades", day = 2020-03-25 }]\n'
    )

    assert source("deribit", file).known_gaps == {
        Gap(InstrumentId.from_str("BTC-OPTIONS.DERIBIT"), TradeTick, date(2020, 3, 25))
    }


@pytest.mark.unit
def test_a_deribit_known_gap_of_trades_covers_every_data_type_of_the_day(
    tmp_path: Path,
) -> None:
    file = tmp_path / "known_gaps.toml"
    file.write_text(
        'deribit = [{ symbol = "BTC", data = "trades", day = 2020-03-25 }]\n'
    )
    deribit = source("deribit", file)

    assert all(
        deribit.is_known_gap("BTC", each, date(2020, 3, 25))
        for each in deribit.data_types
    )
    assert not deribit.is_known_gap("BTC", TradeTick, date(2020, 3, 26))


@pytest.mark.unit
def test_known_gaps_combine_every_configured_source(tmp_path: Path) -> None:
    file = tmp_path / "known_gaps.toml"
    file.write_text(
        "bybit = [\n"
        '  { symbol = "BTCUSDT", data = "trades", day = 2020-03-25 },\n'
        '  { symbol = "ETHUSDT", data = "trades", day = 2020-03-26 },\n'
        "]\n"
    )

    assert known_gaps(file) == {
        Gap(
            InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT"), TradeTick, date(2020, 3, 25)
        ),
        Gap(
            InstrumentId.from_str("ETHUSDT-LINEAR.BYBIT"), TradeTick, date(2020, 3, 26)
        ),
    }


@pytest.mark.unit
def test_a_config_without_sources_has_no_known_gaps(tmp_path: Path) -> None:
    file = tmp_path / "known_gaps.toml"
    file.write_text("")

    assert known_gaps(file) == frozenset()


TRADES_GAP = ListedGap("bybit", "BTCUSDT", "trades", date(2020, 3, 25))
CANDLES_GAP = ListedGap("bybit", "ETHUSDT", "candles", date(2020, 3, 26))


@pytest.mark.unit
def test_listed_known_gaps_name_their_source(tmp_path: Path) -> None:
    file = tmp_path / "known_gaps.toml"
    file.write_text(
        "bybit = [\n"
        '  { symbol = "BTCUSDT", data = "trades", day = 2020-03-25 },\n'
        '  { symbol = "ETHUSDT", data = "candles", day = 2020-03-26 },\n'
        "]\n"
    )

    assert listed_gaps(file) == [TRADES_GAP, CANDLES_GAP]


@pytest.mark.unit
def test_add_known_gaps_appends_them_to_their_source_list(tmp_path: Path) -> None:
    file = tmp_path / "known_gaps.toml"

    add_known_gaps(file, [TRADES_GAP])
    add_known_gaps(file, [CANDLES_GAP])

    assert listed_gaps(file) == [TRADES_GAP, CANDLES_GAP]
    assert source("bybit", file).known_gaps == {
        Gap(
            InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT"), TradeTick, date(2020, 3, 25)
        ),
        Gap(InstrumentId.from_str("ETHUSDT-LINEAR.BYBIT"), Bar, date(2020, 3, 26)),
    }


@pytest.mark.unit
def test_adding_a_listed_gap_again_keeps_one_entry(tmp_path: Path) -> None:
    file = tmp_path / "known_gaps.toml"
    add_known_gaps(file, [TRADES_GAP])

    add_known_gaps(file, [TRADES_GAP, TRADES_GAP])

    assert listed_gaps(file) == [TRADES_GAP]


@pytest.mark.unit
def test_remove_known_gaps_drops_only_those_gaps(tmp_path: Path) -> None:
    file = tmp_path / "known_gaps.toml"
    add_known_gaps(file, [TRADES_GAP, CANDLES_GAP])

    remove_known_gaps(file, [TRADES_GAP])

    assert listed_gaps(file) == [CANDLES_GAP]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("gap", "error"),
    [
        (ListedGap("nope", "BTCUSDT", "trades", date(2020, 3, 25)), UnknownSourceError),
        (
            ListedGap("bybit", "BTCUSDT", "quotes", date(2020, 3, 25)),
            UnsupportedDataTypeError,
        ),
    ],
    ids=["unknown-source", "unknown-data-type"],
)
def test_a_gap_of_an_unknown_source_or_data_type_is_rejected_and_nothing_is_written(
    tmp_path: Path, gap: ListedGap, error: type[Exception]
) -> None:
    file = tmp_path / "known_gaps.toml"
    add_known_gaps(file, [TRADES_GAP])
    before = file.read_bytes()

    with pytest.raises(error):
        add_known_gaps(file, [CANDLES_GAP, gap])

    assert file.read_bytes() == before


@pytest.mark.unit
@pytest.mark.parametrize(
    ("instrument_id", "name"),
    [
        ("BTCUSDT-PERP.BINANCE", "binance"),
        ("BTC-USDT-SWAP.OKX", "okx"),
        ("BTC-USD-PERP.COINBASE_INTX", "coinbase_intx"),
        ("BTCUSDT-LINEAR.BYBIT", "bybit"),
        ("BTC-PERPETUAL.DERIBIT", "deribit"),
    ],
)
def test_the_source_of_an_instrument_is_the_one_of_its_venue(
    instrument_id: str, name: str
) -> None:
    assert source_name(InstrumentId.from_str(instrument_id)) == name


@pytest.mark.unit
def test_an_instrument_of_an_unknown_venue_has_no_source() -> None:
    with pytest.raises(UnknownSourceError, match="no source for the venue KRAKEN"):
        source_name(InstrumentId.from_str("BTC-PERP.KRAKEN"))


CRYPTO_SWAP = (AssetClass.CRYPTOCURRENCY, InstrumentClass.SWAP)
CRYPTO_OPTION = (AssetClass.CRYPTOCURRENCY, InstrumentClass.OPTION)


@pytest.mark.unit
@pytest.mark.parametrize(
    "instrument_id",
    [
        "BTCUSDT-LINEAR.BYBIT",
        "BTCUSDT-PERP.BINANCE",
        "ETH-USDT-SWAP.OKX",
        "BTC-PERP.COINBASE_INTX",
    ],
)
def test_each_source_names_the_class_of_its_symbols(instrument_id: str) -> None:
    traded = InstrumentId.from_str(instrument_id)

    assert source_for(traded).asset_classes(traded) == CRYPTO_SWAP


@pytest.mark.unit
def test_deribit_perpetual_is_a_swap_and_its_options_are_options() -> None:
    perpetual = InstrumentId.from_str("BTC-PERPETUAL.DERIBIT")
    options = InstrumentId.from_str("BTC-OPTIONS.DERIBIT")
    option = InstrumentId.from_str("BTC-27DEC24-60000-C.DERIBIT")

    deribit = source_for(perpetual)

    assert isinstance(deribit, DeribitSource)
    assert deribit.asset_classes(perpetual) == CRYPTO_SWAP
    assert deribit.asset_classes(options) == CRYPTO_OPTION
    assert deribit.asset_classes(option) == CRYPTO_OPTION


@pytest.mark.unit
def test_source_says_whether_it_serves_mark_prices() -> None:
    bybit = InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")
    binance = InstrumentId.from_str("BTCUSDT-PERP.BINANCE")
    perpetual = InstrumentId.from_str("BTC-PERPETUAL.DERIBIT")
    option = InstrumentId.from_str("BTC-27DEC24-60000-C.DERIBIT")

    assert source_for(bybit).serves_marks(bybit)
    assert not source_for(binance).serves_marks(binance)
    assert not source_for(perpetual).serves_marks(perpetual)
    assert source_for(option).serves_marks(option)
