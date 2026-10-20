"""What the tests of the kline sources share."""

import asyncio
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from sbt2.data import DayRange, DownloadOptions, DownloadRequest, Outcome, download
from sbt2.data.sources import Source

DAY = date(2025, 1, 1)
SNAPSHOT_DAY = date(2026, 10, 19)
DAY_NANOS = pd.Timestamp(DAY, tz="UTC").value
MINUTE_NANOS = 60_000_000_000
CLOSES = [DAY_NANOS + n * MINUTE_NANOS - 1 for n in range(1, 1441)]


def downloaded(source: Source, symbol: str, root: Path) -> list[Outcome]:
    """The outcomes of downloading the day and the snapshot of ``symbol``."""
    request = DownloadRequest(DayRange((symbol,), DAY, DAY), SNAPSHOT_DAY)
    tally = download(source, request, DownloadOptions(root, retries=0, backoff=0.0))
    return [each.outcome for each in tally.results]


def snapshot_instrument(source: Source, symbol: str, root: Path) -> Any:
    """The instrument of ``symbol``'s snapshot, fetched on its own."""
    raw = source.instrument_snapshot(symbol, SNAPSHOT_DAY)
    assert callable(raw.origin)
    path = root / raw.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(asyncio.run(raw.origin()))
    return source.parse_instruments(path)[source.instrument_id(symbol)]
