from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import override

import pytest
from deribit_replay import deribit_replay
from local_source import (
    INSTRUMENT_ID,
    SYMBOL,
    LocalSource,
    RawFolder,
    start_of,
    write_snapshot,
)
from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestNode,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.common import Cache, LoggerConfig, LogLevel
from nautilus_trader.execution import FixedFeeModel
from nautilus_trader.model import (
    FundingRateUpdate,
    MarkPriceUpdate,
    Money,
    NautilusDataType,
    OrderSide,
    PositionAdjustmentType,
    Quantity,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.trading import Strategy

from sbt2.data import (
    DayRange,
    DownloadOptions,
    DownloadRequest,
    IngestOptions,
    IngestOutcome,
    IngestRequest,
    Outcome,
    Source,
    download,
    ingest,
)

DAY = date(2024, 1, 1)
HOUR = 3_600_000_000_000
STREAMED = [
    NautilusDataType.TradeTick,
    NautilusDataType.MarkPriceUpdate,
    NautilusDataType.FundingRateUpdate,
]


class BuyOneOnFirstTrade(Strategy):
    def on_start(self) -> None:
        self.bought = False
        self.subscribe_trades(INSTRUMENT_ID)

    @override
    def on_trade(self, trade: TradeTick) -> None:
        if self.bought:
            return
        self.bought = True
        order = self.order_factory.market(
            INSTRUMENT_ID, OrderSide.BUY, Quantity.from_str("1.000")
        )
        self.submit_order(order)


def ingest_one_day(tmp_path: Path) -> Path:
    raw, catalog = tmp_path / "raw", tmp_path / "catalog"
    write_snapshot(raw, DAY)
    hours = [start_of(DAY) + hour * HOUR for hour in range(24)]
    RawFolder(raw).write_day(TradeTick, DAY, hours)
    RawFolder(raw).write_day(MarkPriceUpdate, DAY, hours)
    RawFolder(raw).write_day(FundingRateUpdate, DAY, [hours[8], hours[16]])
    request = IngestRequest(DayRange((SYMBOL,), DAY, DAY))
    ingest(LocalSource(), request, IngestOptions(raw, catalog))
    return catalog


def run_long_one_btc(catalog: Path) -> Cache:
    venue = BacktestVenueConfig(
        INSTRUMENT_ID.venue.value,
        "NETTING",
        "MARGIN",
        ["10000 USDT"],
        default_leverage=Decimal(10),
        fee_model=FixedFeeModel(Money.from_str("0 USDT")),
    )
    streams = [
        BacktestDataConfig(each, str(catalog), instrument_id=INSTRUMENT_ID)
        for each in STREAMED
    ]
    config = BacktestRunConfig(
        [venue],
        streams,
        engine=BacktestEngineConfig(logging=LoggerConfig(stdout_level=LogLevel.ERROR)),
        dispose_on_completion=False,
    )
    node = BacktestNode([config])
    node.build()
    node.add_strategy(config.id, BuyOneOnFirstTrade())
    node.run()
    return node.get_engine_cache(config.id)


def funding_payments(cache: Cache) -> list[Money]:
    return [
        adjustment.pnl_change
        for position in cache.positions()
        for adjustment in position.adjustments()
        if adjustment.adjustment_type == PositionAdjustmentType.FUNDING
        and adjustment.pnl_change is not None
    ]


@pytest.mark.integration
def test_ingested_funding_streams_back_and_the_venue_settles_it(
    tmp_path: Path,
) -> None:
    cache = run_long_one_btc(ingest_one_day(tmp_path))

    assert funding_payments(cache) == [Money.from_str("-5.00 USDT")] * 2


DERIBIT_DAY = date(2025, 1, 1)
DERIBIT_SNAPSHOT_DAY = date(2026, 10, 7)
PUT_88K = "BTC-10JAN25-88000-P.DERIBIT"
TRADED = {
    "BTC-10JAN25-88000-P.DERIBIT": 4,
    "BTC-31JAN25-135000-C.DERIBIT": 1,
    "BTC-31JAN25-83000-P.DERIBIT": 2,
    "BTC-3JAN25-96000-P.DERIBIT": 1,
}


@pytest.fixture
def deribit() -> Iterator[Source]:
    with deribit_replay() as source:
        yield source


def download_and_ingest(source: Source, tmp_path: Path) -> list[IngestOutcome]:
    days = DayRange(("BTC",), DERIBIT_DAY, DERIBIT_DAY)
    fetched = download(
        source,
        DownloadRequest(days, DERIBIT_SNAPSHOT_DAY),
        DownloadOptions(tmp_path / "raw"),
    )
    assert {each.outcome for each in fetched.results} == {Outcome.FETCHED}
    tally = ingest(
        source,
        IngestRequest(days),
        IngestOptions(tmp_path / "raw", tmp_path / "catalog"),
    )
    return [each.outcome for each in tally.results]


def stored_trades(tmp_path: Path, instrument_id: str) -> list[TradeTick]:
    catalog = ParquetDataCatalog(str(tmp_path / "catalog"))
    return list(catalog.query(NautilusDataType.TradeTick, [instrument_id]))


@pytest.mark.integration
def test_deribit_option_trades_round_trip_through_the_catalog(
    deribit: Source, tmp_path: Path
) -> None:
    assert download_and_ingest(deribit, tmp_path) == [IngestOutcome.WRITTEN]

    stored = {each: stored_trades(tmp_path, each) for each in TRADED}

    assert {each: len(ticks) for each, ticks in stored.items()} == TRADED
    first = stored[PUT_88K][0]
    assert (str(first.price), str(first.size), str(first.trade_id)) == (
        "0.0120",
        "3.2",
        "338110741",
    )
    assert first.ts_event == 1_735_689_642_010 * 1_000_000


@pytest.mark.integration
def test_only_the_contracts_traded_are_stored_as_instruments(
    deribit: Source, tmp_path: Path
) -> None:
    download_and_ingest(deribit, tmp_path)

    stored = ParquetDataCatalog(str(tmp_path / "catalog")).instruments()

    assert {str(each.id) for each in stored} == set(TRADED)


@pytest.mark.integration
def test_a_rerun_skips_the_day_already_in_the_catalog(
    deribit: Source, tmp_path: Path
) -> None:
    download_and_ingest(deribit, tmp_path)
    days = DayRange(("BTC",), DERIBIT_DAY, DERIBIT_DAY)

    tally = ingest(
        deribit,
        IngestRequest(days),
        IngestOptions(tmp_path / "raw", tmp_path / "catalog"),
    )

    assert [each.outcome for each in tally.results] == [IngestOutcome.SKIPPED]
    assert len(stored_trades(tmp_path, PUT_88K)) == TRADED[PUT_88K]
