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
BTC_INDEX = "BTC_USD.DERIBIT"
BTC_DVOL = "BTC_DVOL.DERIBIT"
BTC_DELIVERY = "BTC_USD_DELIVERY.DERIBIT"
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
    return download_and_ingest_symbol(source, "BTC", tmp_path)


def download_and_ingest_symbol(
    source: Source, symbol: str, tmp_path: Path
) -> list[IngestOutcome]:
    days = DayRange((symbol,), DERIBIT_DAY, DERIBIT_DAY)
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
    assert download_and_ingest(deribit, tmp_path) == [IngestOutcome.WRITTEN] * (
        len(deribit.data_types) - 1  # the options have no funding
    )

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
def test_deribit_mark_prices_round_trip_through_the_catalog(
    deribit: Source, tmp_path: Path
) -> None:
    download_and_ingest(deribit, tmp_path)

    catalog = ParquetDataCatalog(str(tmp_path / "catalog"))
    stored = {
        each: list(catalog.query(NautilusDataType.MarkPriceUpdate, [each]))
        for each in TRADED
    }

    assert {each: len(marks) for each, marks in stored.items()} == TRADED
    first = stored[PUT_88K][0]
    assert str(first.value) == "0.01163879"
    assert first.ts_event == 1_735_689_642_010 * 1_000_000


@pytest.mark.integration
def test_deribit_option_greeks_round_trip_through_the_catalog(
    deribit: Source, tmp_path: Path
) -> None:
    download_and_ingest(deribit, tmp_path)

    catalog = ParquetDataCatalog(str(tmp_path / "catalog"))
    stored = {
        each: list(catalog.query(NautilusDataType.OptionGreeks, [each]))
        for each in TRADED
    }

    assert {each: len(greeks) for each, greeks in stored.items()} == TRADED
    first = stored[PUT_88K][0]
    assert first.mark_iv == 0.5544
    assert first.underlying_price == 93374.45
    assert first.delta < 0
    assert first.ts_event == 1_735_689_642_010 * 1_000_000


@pytest.mark.integration
def test_deribit_index_prices_round_trip_through_the_catalog(
    deribit: Source, tmp_path: Path
) -> None:
    download_and_ingest(deribit, tmp_path)

    catalog = ParquetDataCatalog(str(tmp_path / "catalog"))
    stored = list(catalog.query(NautilusDataType.IndexPriceUpdate, [BTC_INDEX]))

    assert len(stored) == sum(TRADED.values())
    assert [str(each.value) for each in stored][:2] == ["93369.56", "93366.92"]
    assert [each.ts_event for each in stored] == sorted(
        each.ts_event for each in stored
    )


@pytest.mark.integration
def test_only_the_contracts_traded_and_their_index_are_stored_as_instruments(
    deribit: Source, tmp_path: Path
) -> None:
    download_and_ingest(deribit, tmp_path)

    stored = ParquetDataCatalog(str(tmp_path / "catalog")).instruments()

    assert {str(each.id) for each in stored} == {*TRADED, BTC_INDEX}


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

    assert [each.outcome for each in tally.results] == [IngestOutcome.SKIPPED] * (
        len(deribit.data_types) - 1  # the options have no funding
    )
    assert len(stored_trades(tmp_path, PUT_88K)) == TRADED[PUT_88K]


@pytest.mark.integration
def test_a_rerun_skips_the_marks_greeks_and_index_already_in_the_catalog(
    deribit: Source, tmp_path: Path
) -> None:
    download_and_ingest(deribit, tmp_path)
    days = DayRange(
        ("BTC",),
        DERIBIT_DAY,
        DERIBIT_DAY,
        ("MarkPriceUpdate", "OptionGreeks", "IndexPriceUpdate"),
    )

    tally = ingest(
        deribit,
        IngestRequest(days),
        IngestOptions(tmp_path / "raw", tmp_path / "catalog"),
    )

    assert [each.outcome for each in tally.results] == [IngestOutcome.SKIPPED] * 3
    catalog = ParquetDataCatalog(str(tmp_path / "catalog"))
    assert len(catalog.query(NautilusDataType.IndexPriceUpdate, [BTC_INDEX])) == 8


@pytest.mark.integration
def test_deribit_dvol_round_trips_through_the_catalog(
    deribit: Source, tmp_path: Path
) -> None:
    assert download_and_ingest_symbol(deribit, "BTC_DVOL", tmp_path) == [
        IngestOutcome.WRITTEN
    ]

    catalog = ParquetDataCatalog(str(tmp_path / "catalog"))
    stored = list(catalog.query(NautilusDataType.IndexPriceUpdate, [BTC_DVOL]))
    assert [str(each.id) for each in catalog.instruments()] == [BTC_DVOL]
    assert len(stored) == 24
    assert [str(each.value) for each in stored][:2] == ["60.03", "60.26"]
    assert stored[1].ts_event - stored[0].ts_event == 3_600 * 1_000_000_000


@pytest.mark.integration
def test_deribit_delivery_prices_round_trip_through_the_catalog(
    deribit: Source, tmp_path: Path
) -> None:
    assert download_and_ingest_symbol(deribit, "BTC_USD_DELIVERY", tmp_path) == [
        IngestOutcome.WRITTEN
    ]

    catalog = ParquetDataCatalog(str(tmp_path / "catalog"))
    (stored,) = catalog.query(NautilusDataType.IndexPriceUpdate, [BTC_DELIVERY])
    assert str(stored.value) == "93539.00"
    assert stored.ts_event == (1_735_689_600 + 8 * 3_600) * 1_000_000_000
