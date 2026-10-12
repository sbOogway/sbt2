"""Downloads a real day from Deribit and ingests it; run with ``pytest -m live``."""

import math
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from nautilus_trader.model import (
    CryptoOption,
    IndexInstrument,
    IndexPriceUpdate,
    MarkPriceUpdate,
    NautilusDataType,
    OptionGreeks,
    TradeTick,
)
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
    assert {each.outcome for each in written.results} == {IngestOutcome.WRITTEN}
    stored = ParquetDataCatalog(str(catalog))
    contracts = [
        each for each in stored.instruments() if not isinstance(each, IndexInstrument)
    ]
    assert len(contracts) > 50
    assert all(isinstance(each, CryptoOption) for each in contracts)
    ticks = stored.query(NautilusDataType.TradeTick)
    assert len(ticks) > 1000
    assert all(isinstance(each, TradeTick) for each in ticks)
    assert all(DAY_START <= each.ts_event < DAY_END for each in ticks)
    assert {each.instrument_id for each in ticks} <= {each.id for each in contracts}


@pytest.mark.live
@pytest.mark.e2e
def test_one_day_of_btc_option_marks_greeks_and_index_downloads_and_ingests(
    tmp_path: Path,
) -> None:
    deribit = source("deribit", tmp_path / "known_gaps.toml")
    days = DayRange(("BTC",), DAY, DAY)
    raw, catalog = tmp_path / "raw", tmp_path / "catalog"

    download(deribit, DownloadRequest(days), DownloadOptions(raw))
    written = ingest(deribit, IngestRequest(days), IngestOptions(raw, catalog))

    assert {each.outcome for each in written.results} == {IngestOutcome.WRITTEN}
    stored = ParquetDataCatalog(str(catalog))
    ticks = stored.query(NautilusDataType.TradeTick)
    marks = stored.query(NautilusDataType.MarkPriceUpdate)
    greeks = stored.query(NautilusDataType.OptionGreeks)
    index = stored.query(NautilusDataType.IndexPriceUpdate)
    assert len(marks) == len(index) == len(ticks)
    assert 0 < len(greeks) <= len(ticks)
    assert all(isinstance(each, MarkPriceUpdate) for each in marks)
    assert all(isinstance(each, OptionGreeks) for each in greeks)
    assert all(isinstance(each, IndexPriceUpdate) for each in index)
    assert {str(each.instrument_id) for each in index} == {"BTC_USD.DERIBIT"}
    assert all(each.value.as_double() > 10_000 for each in index)
    assert all(0 < each.mark_iv < 20 for each in greeks)
    assert all(
        math.isfinite(each.delta) and math.isfinite(each.theta) for each in greeks
    )


@pytest.mark.live
@pytest.mark.e2e
def test_one_day_of_btc_dvol_and_delivery_price_downloads_and_ingests(
    tmp_path: Path,
) -> None:
    deribit = source("deribit", tmp_path / "known_gaps.toml")
    days = DayRange(("BTC_DVOL", "BTC_USD_DELIVERY"), DAY, DAY)
    raw, catalog = tmp_path / "raw", tmp_path / "catalog"

    fetched = download(deribit, DownloadRequest(days), DownloadOptions(raw))
    written = ingest(deribit, IngestRequest(days), IngestOptions(raw, catalog))

    assert {each.outcome for each in fetched.results} == {Outcome.FETCHED}
    assert {each.outcome for each in written.results} == {IngestOutcome.WRITTEN}
    stored = ParquetDataCatalog(str(catalog))
    dvol = stored.query(NautilusDataType.IndexPriceUpdate, ["BTC_DVOL.DERIBIT"])
    (delivery,) = stored.query(
        NautilusDataType.IndexPriceUpdate, ["BTC_USD_DELIVERY.DERIBIT"]
    )
    assert len(dvol) == 24
    assert all(DAY_START <= each.ts_event < DAY_END for each in dvol)
    assert all(10 < each.value.as_double() < 300 for each in dvol)
    assert delivery.value.as_double() == 93539.0
    assert delivery.ts_event == DAY_START + pd.Timedelta(hours=8).value
