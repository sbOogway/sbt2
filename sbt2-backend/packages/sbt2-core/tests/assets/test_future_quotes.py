from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from dated_catalog import EXPIRY, START, build_bars, future, spot, write_delivery
from nautilus_trader.backtest import BacktestDataConfig
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    AssetClass,
    Bar,
    InstrumentClass,
    MarkPriceUpdate,
    NautilusDataType,
)
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.core.assets import (
    NoDeliveryPriceError,
    NoMarksError,
    QuoteJob,
    asset_profile,
)
from sbt2.data import Catalog, Window

TWO_DAYS = (START, START + timedelta(days=2))


def write_quotes(
    source: Path, coin: str, span: tuple[datetime, datetime] = TWO_DAYS
) -> tuple[list[BacktestDataConfig], ParquetDataCatalog]:
    """Write the quotes of the coin's future from ``source`` over ``span``, and
    return their configs and catalog."""
    target = source.parent / "target"
    target.mkdir()
    profile = asset_profile(AssetClass.CRYPTOCURRENCY, InstrumentClass.FUTURE)
    job = QuoteJob(source, [future(coin).id], span, {"marks": "bars"})
    return profile.quotes.write(job, target), ParquetDataCatalog(str(target))


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
def test_spot_marks_equal_bar_closes(tmp_path: Path) -> None:
    instrument = spot()
    source, target = tmp_path / "source", tmp_path / "target"
    build_bars(source, instrument)
    target.mkdir()
    profile = asset_profile(AssetClass.CRYPTOCURRENCY, InstrumentClass.SPOT)
    job = QuoteJob(source, [instrument.id], TWO_DAYS, {"marks": "bars"})

    configs = profile.quotes.write(job, target)

    assert [each.data_type for each in configs] == [NautilusDataType.MarkPriceUpdate]
    marks = Catalog(target).frame(instrument.id, MarkPriceUpdate, Window(*TWO_DAYS))
    bars = Catalog(source).frame(instrument.id, Bar, Window(*TWO_DAYS))
    assert marks["price"].tolist() == bars["close"].tolist()
    assert marks.index.equals(bars.index)


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


@pytest.mark.integration
@pytest.mark.parametrize("coin", ["BTC", "ETH"])
def test_future_settlement_quotes_use_delivery(tmp_path: Path, coin: str) -> None:
    source = tmp_path / "source"
    build_bars(source, future(coin))
    write_delivery(
        source,
        coin,
        {EXPIRY - timedelta(hours=1): 51_234.3, EXPIRY + timedelta(hours=1): 60_000},
    )

    configs, target = write_quotes(source, coin)

    quoted = [each for each in configs if each.data_type == NautilusDataType.QuoteTick]
    assert [each.instrument_ids for each in quoted] == [[future(coin).id]]
    quotes = target.query(NautilusDataType.QuoteTick, [str(future(coin).id)])
    expiry = dt_to_unix_nanos(EXPIRY)
    assert [each.ts_event for each in quotes] == [expiry - 2, expiry]
    assert {(str(each.bid_price), str(each.ask_price)) for each in quotes} == {
        ("51234.5", "51234.5")
    }


@pytest.mark.integration
def test_future_without_expiry_in_window_needs_no_delivery(tmp_path: Path) -> None:
    source = tmp_path / "source"
    build_bars(source, future())

    configs, target = write_quotes(source, "BTC", (START, EXPIRY - timedelta(hours=1)))

    assert [each.data_type for each in configs] == [NautilusDataType.MarkPriceUpdate]
    assert target.query(NautilusDataType.QuoteTick, [str(future().id)]) == []


@pytest.mark.integration
@pytest.mark.parametrize("delivery", [{}, {EXPIRY + timedelta(hours=1): 60_000.0}])
def test_missing_future_delivery_names_contract_and_day(
    tmp_path: Path, delivery: dict[datetime, float]
) -> None:
    source = tmp_path / "source"
    build_bars(source, future())
    if delivery:
        write_delivery(source, "BTC", delivery)

    with pytest.raises(NoDeliveryPriceError, match=r"2024-01-02.*BTC-2JAN24\.DERIBIT"):
        write_quotes(source, "BTC")
