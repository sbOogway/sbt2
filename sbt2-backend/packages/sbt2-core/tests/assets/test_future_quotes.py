from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest
from dated_catalog import START, build_bars, future
from nautilus_trader.model import AssetClass, InstrumentClass, MarkPriceUpdate
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.core.assets import NoMarksError, QuoteJob, asset_profile
from sbt2.data import Catalog, Window


@pytest.mark.integration
@pytest.mark.parametrize("coin", ["BTC", "ETH"])
def test_future_marks_equal_bar_closes(tmp_path: Path, coin: str) -> None:
    instrument = future(coin)
    source, target = tmp_path / "source", tmp_path / "target"
    build_bars(source, instrument)
    target.mkdir()
    profile = asset_profile(AssetClass.CRYPTOCURRENCY, InstrumentClass.FUTURE)
    span = (START, START + timedelta(days=1))
    job = QuoteJob(source, [instrument.id], span, {"marks": "bars"})

    configs = profile.quotes.write(job, target)

    assert configs
    marks = Catalog(target).frame(instrument.id, MarkPriceUpdate, Window(*span))
    assert len(marks) == 1440
    assert marks["price"].tolist() == [50_000 + 100 * (m // 60) for m in range(1440)]
    assert marks.index[0] == pd.Timestamp(START) + timedelta(minutes=1) - pd.Timedelta(
        1, "ns"
    )
    assert marks.index[-1] < span[1]


@pytest.mark.integration
def test_missing_bars_raise_no_marks(tmp_path: Path) -> None:
    instrument = future()
    source = tmp_path / "source"
    source.mkdir()
    (tmp_path / "target").mkdir()
    ParquetDataCatalog(str(source)).write_instruments([instrument])
    profile = asset_profile(AssetClass.CRYPTOCURRENCY, InstrumentClass.FUTURE)
    job = QuoteJob(
        source, [instrument.id], (START, START + timedelta(days=1)), {"marks": "bars"}
    )
    with pytest.raises(NoMarksError, match="1-minute bars"):
        profile.quotes.write(job, tmp_path / "target")
