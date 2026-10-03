from datetime import date
from pathlib import Path

import pytest
from nautilus_trader.model import Bar, InstrumentId, TradeTick

from sbt2.core.data.sources import Gap, UnknownSourceError, known_gaps, source


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
