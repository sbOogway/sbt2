from datetime import date
from pathlib import Path
from typing import Any

import pytest
from served_source import ServedSource

from sbt2.run import DataFolders, SnapshotBufferError, preflight
from sbt2.spec import ResolvedRunSpec, load

VENUES = """
[test_linear]
name = "BYBIT"
source = "served"
asset_class = "CRYPTOCURRENCY"
instrument_class = "SWAP"
"""
DAY = date(2024, 1, 1)
# 1,000,000 seconds after the start, the most 1s snapshots nautilus keeps.
LAST_SNAPSHOT = "2024-01-12T15:46:40"


def spec(tmp_path: Path, **values: Any) -> ResolvedRunSpec:
    lines = {
        "strategy": '"run_strategies:BuyThenSell"',
        "instruments": '["BTCUSDT-LINEAR.BYBIT"]',
        "start": "2024-01-01T02:00:00",
        "end": "2024-01-03",
        "venue": '"test_linear"',
        "capital": '"10000 USDT"',
        **values,
    }
    path, venues = tmp_path / "spec.toml", tmp_path / "venues.toml"
    path.write_text("".join(f"{key} = {value}\n" for key, value in lines.items()))
    venues.write_text(VENUES)
    return load(path, venue_profiles=venues)


@pytest.fixture
def folders(tmp_path: Path) -> DataFolders:
    return DataFolders(raw=tmp_path / "raw", catalog=tmp_path / "catalog")


def test_a_segment_over_the_snapshot_buffer_fails_before_fetching(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, date(2024, 1, 12))
    run = spec(tmp_path, end="2024-01-12T15:46:41", equity_interval='"1s"')

    with pytest.raises(SnapshotBufferError, match="1,000,001"):
        preflight(run, source, folders)
    assert source.fetched == []


def test_a_segment_filling_the_snapshot_buffer_exactly_passes(
    tmp_path: Path, folders: DataFolders
) -> None:
    source = ServedSource()
    source.serve(DAY, date(2024, 1, 12))
    run = spec(tmp_path, end=LAST_SNAPSHOT, equity_interval='"1s"')

    assert preflight(run, source, folders) == ()
