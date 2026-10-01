from datetime import date
from pathlib import Path

import pytest
from served_source import ServedSource

from sbt2 import data

SPEC = """
strategy = "strategies.ma_cross:MovingAverageCross"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
venue = "served_linear"
capital = "10000 USDT"

[params]
fast = 1
slow = 2
"""
VENUES = """
[served_linear]
name = "BYBIT"
source = "served"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
fee_model = { path = "nautilus_trader.execution:MakerTakerFeeModel", config = { maker_rate = "0.0002", taker_rate = "0.00055" } }
"""
DAY = date(2024, 1, 1)
NEXT_DAY = date(2024, 1, 2)
VALIDATION_DAY = date(2024, 1, 3)


def served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: ServedSource
) -> Path:
    """A spec run from ``tmp_path``, whose venue's data comes from ``source``."""
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "venues.toml").write_text(VENUES)
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(data, "source", lambda _name, _config: source)
    return spec


def without_a_part(spec: Path) -> Path:
    spec.write_text(spec.read_text().replace('part = "train"\n', ""))
    return spec
