"""Downloads a real day from Deribit and ingests it; run with ``pytest -m live``."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model import NautilusDataType, OptionContract, TradeTick
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.data import (
    DayRange,
    DownloadOptions,
    DownloadRequest,
    IngestOptions,
    IngestOutcome,
    IngestRequest,
    Outcome,
    download,
    ingest,
    source,
)

DAY = date(2025, 1, 1)
DAY_START = pd.Timestamp(DAY, tz="UTC").value
DAY_END = DAY_START + pd.Timedelta(days=1).value


@pytest.mark.live
@pytest.mark.e2e
def test_one_day_of_btc_option_trades_downloads_and_ingests(tmp_path: Path) -> None:
    deribit = source("deribit", tmp_path / "known_gaps.toml")
    days = DayRange(("BTC",), DAY, DAY)
    raw, catalog = tmp_path / "raw", tmp_path / "catalog"

    fetched = download(deribit, DownloadRequest(days), DownloadOptions(raw))
    written = ingest(deribit, IngestRequest(days), IngestOptions(raw, catalog))

    assert {each.outcome for each in fetched.results} == {Outcome.FETCHED}
    assert [each.outcome for each in written.results] == [IngestOutcome.WRITTEN]
    stored = ParquetDataCatalog(str(catalog))
    contracts = stored.instruments()
    assert len(contracts) > 50
    assert all(isinstance(each, OptionContract) for each in contracts)
    ticks = stored.query(NautilusDataType.TradeTick)
    assert len(ticks) > 1000
    assert all(isinstance(each, TradeTick) for each in ticks)
    assert all(DAY_START <= each.ts_event < DAY_END for each in ticks)
    assert {each.instrument_id for each in ticks} <= {each.id for each in contracts}
