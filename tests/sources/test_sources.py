from datetime import date
from pathlib import Path

import pytest
from nautilus_trader.model import Bar, InstrumentId, TradeTick

from sbt2.sources import Gap, UnknownSourceError, known_gaps, source

REPO_CONFIG = Path(__file__).parents[2] / "config" / "sources.toml"


def test_repo_config_builds_bybit_without_known_gaps() -> None:
    assert source("bybit", REPO_CONFIG).known_gaps == frozenset()


def test_known_gaps_come_from_the_config(tmp_path: Path) -> None:
    config = tmp_path / "sources.toml"
    config.write_text(
        "[bybit]\n"
        'known_gaps = [{ symbol = "BTCUSDT", data = "trades", day = 2020-03-25 }]\n'
    )

    assert source("bybit", config).known_gaps == {
        Gap(InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT"), TradeTick, date(2020, 3, 25))
    }


def test_known_gaps_can_name_candles(tmp_path: Path) -> None:
    config = tmp_path / "sources.toml"
    config.write_text(
        "[bybit]\n"
        'known_gaps = [{ symbol = "BTCUSDT", data = "candles", day = 2020-03-25 }]\n'
    )

    assert source("bybit", config).known_gaps == {
        Gap(InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT"), Bar, date(2020, 3, 25))
    }


def test_unknown_source_is_refused() -> None:
    with pytest.raises(UnknownSourceError, match="known: bybit"):
        source("nope", REPO_CONFIG)


def test_known_gaps_combine_every_configured_source(tmp_path: Path) -> None:
    config = tmp_path / "sources.toml"
    config.write_text(
        "[bybit]\n"
        "known_gaps = [\n"
        '  { symbol = "BTCUSDT", data = "trades", day = 2020-03-25 },\n'
        '  { symbol = "ETHUSDT", data = "trades", day = 2020-03-26 },\n'
        "]\n"
    )

    assert known_gaps(config) == {
        Gap(
            InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT"), TradeTick, date(2020, 3, 25)
        ),
        Gap(
            InstrumentId.from_str("ETHUSDT-LINEAR.BYBIT"), TradeTick, date(2020, 3, 26)
        ),
    }


def test_a_config_without_sources_has_no_known_gaps(tmp_path: Path) -> None:
    config = tmp_path / "sources.toml"
    config.write_text("")

    assert known_gaps(config) == frozenset()
