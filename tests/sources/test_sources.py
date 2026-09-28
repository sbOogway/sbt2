from datetime import date
from pathlib import Path

import pytest
from nautilus_trader.model import InstrumentId, TradeTick

from sbt2.sources import Gap, UnknownSourceError, source

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


def test_unknown_source_is_refused() -> None:
    with pytest.raises(UnknownSourceError, match="known: bybit"):
        source("nope", REPO_CONFIG)
