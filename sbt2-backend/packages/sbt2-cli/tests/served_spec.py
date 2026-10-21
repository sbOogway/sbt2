from datetime import date
from pathlib import Path

import pytest

from sbt2 import data
from sbt2.data.testing import ServedSource

SPEC = """
strategy = "crossover:MovingAverageCross"
instruments = ["BTCUSDT-LINEAR.BYBIT"]
period = [2024-01-01T02:00:00, 2024-01-05]
split = { validation_start = 2024-01-03, test_start = 2024-01-04 }
part = "train"
execution = { fee_model = { kind = "maker_taker", config = { maker_rate = "0.0002", taker_rate = "0.00055" } } }
capital = "10000 USDT"

[params]
fast = 1
slow = 2
"""
DAY = date(2024, 1, 1)
NEXT_DAY = date(2024, 1, 2)
VALIDATION_DAY = date(2024, 1, 3)


def served(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: ServedSource
) -> Path:
    """A spec run from ``tmp_path`` on the data root ``tmp_path/data``, whose
    venue's data comes from ``source``."""
    spec = tmp_path / "spec.toml"
    spec.write_text(SPEC)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SBT2_DATA", str(tmp_path / "data"))
    monkeypatch.setattr(data, "source", lambda _name, _config: source)
    return spec


def without_a_part(spec: Path) -> Path:
    spec.write_text(spec.read_text().replace('part = "train"\n', ""))
    return spec
