from datetime import date
from pathlib import Path

import pytest
from nautilus_trader.model import Bar, InstrumentId, TradeTick

from sbt2.data.sources import (
    Gap,
    ListedGap,
    UnknownSourceError,
    UnsupportedDataTypeError,
    add_known_gaps,
    known_gaps,
    listed_gaps,
    remove_known_gaps,
    source,
)
from sbt2.data.sources.deribit import DeribitSource


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
    with pytest.raises(UnknownSourceError, match="known: bybit"):
        source("nope", tmp_path / "known_gaps.toml")


@pytest.mark.unit
def test_deribit_is_a_listed_source(tmp_path: Path) -> None:
    assert isinstance(source("deribit", tmp_path / "known_gaps.toml"), DeribitSource)


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
