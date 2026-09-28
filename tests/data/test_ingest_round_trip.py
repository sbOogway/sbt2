from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from local_source import (
    INSTRUMENT_ID,
    SYMBOL,
    LocalSource,
    start_of,
    write_day,
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
from nautilus_trader.trading import Strategy

from sbt2.data import IngestOptions, IngestRequest, ingest

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
    write_day(raw, TradeTick, DAY, hours)
    write_day(raw, MarkPriceUpdate, DAY, hours)
    write_day(raw, FundingRateUpdate, DAY, [hours[8], hours[16]])
    request = IngestRequest((SYMBOL,), DAY, DAY)
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
