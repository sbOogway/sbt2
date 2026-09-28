from pathlib import Path

import pytest
from catalog_kit import day_bounds, new_catalog, write_zero_rows
from kit import HOUR, INSTRUMENT_ID, mark, perpetual, quiet_engine_config, trade, venues
from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestNode,
    BacktestResult,
    BacktestRunConfig,
)
from nautilus_trader.model import (
    MarkPriceUpdate,
    NautilusDataType,
    TradeTick,
)
from nautilus_trader.persistence import ParquetDataCatalog
from nautilus_trader.trading import Strategy

pytestmark = pytest.mark.characterization

TRADES = NautilusDataType.TradeTick
MARKS = NautilusDataType.MarkPriceUpdate
FULL_DAYS = (0, 2)
EMPTY_DAY = 1
DAYS = 3


def hours(day: int) -> list[int]:
    start, end = day_bounds(day)
    return list(range(start, end, HOUR))


def write_full_day(catalog: ParquetDataCatalog, day: int) -> None:
    bounds = day_bounds(day)
    catalog.write_trade_ticks([trade(ts) for ts in hours(day)], *bounds)
    catalog.write_mark_price_updates([mark(ts) for ts in hours(day)], *bounds)


def build_catalog_with_an_empty_middle_day(path: Path) -> ParquetDataCatalog:
    catalog = new_catalog(path)
    catalog.write_instruments([perpetual()])
    for day in FULL_DAYS:
        write_full_day(catalog, day)
    write_zero_rows(path, TradeTick, day_bounds(EMPTY_DAY))
    write_zero_rows(path, MarkPriceUpdate, day_bounds(EMPTY_DAY))
    return catalog


@pytest.fixture
def catalog(tmp_path: Path) -> ParquetDataCatalog:
    return build_catalog_with_an_empty_middle_day(tmp_path)


def test_catalog_writers_write_no_file_for_no_rows(tmp_path: Path) -> None:
    catalog = new_catalog(tmp_path)

    assert catalog.write_trade_ticks([], *day_bounds(0)) == ""
    assert catalog.write_mark_price_updates([], *day_bounds(0)) == ""
    assert list(tmp_path.rglob("*.parquet")) == []


@pytest.mark.parametrize("data_type", [TRADES, MARKS])
def test_zero_row_day_file_counts_as_a_covered_interval(
    catalog: ParquetDataCatalog, data_type: NautilusDataType
) -> None:
    intervals = catalog.get_intervals(data_type, str(INSTRUMENT_ID))

    assert intervals == [day_bounds(day) for day in range(DAYS)]


@pytest.mark.parametrize("data_type", [TRADES, MARKS])
def test_zero_row_day_file_leaves_no_missing_interval(
    catalog: ParquetDataCatalog, data_type: NautilusDataType
) -> None:
    start, _ = day_bounds(0)
    _, end = day_bounds(DAYS - 1)
    missing = catalog.get_missing_intervals_for_request(
        start, end, data_type, str(INSTRUMENT_ID)
    )

    assert missing == []


def test_zero_row_day_file_adds_no_rows(catalog: ParquetDataCatalog) -> None:
    expected = [trade(ts) for day in FULL_DAYS for ts in hours(day)]

    assert catalog.query(TRADES) == expected


class RecordTrades(Strategy):
    def on_start(self) -> None:
        self.seen: list[int] = []
        self.subscribe_trades(INSTRUMENT_ID)

    def on_trade(self, trade: TradeTick) -> None:
        self.seen.append(trade.ts_event)


def run_over_catalog(path: Path) -> tuple[BacktestResult, RecordTrades]:
    streams = [
        BacktestDataConfig(data_type, str(path), instrument_id=INSTRUMENT_ID)
        for data_type in (TRADES, MARKS)
    ]
    config = BacktestRunConfig(venues(), streams, engine=quiet_engine_config())
    node = BacktestNode([config])
    node.build()
    strategy = RecordTrades()
    node.add_strategy(config.id, strategy)
    [result] = node.run()
    return result, strategy


def test_node_streams_across_a_zero_row_day(tmp_path: Path) -> None:
    build_catalog_with_an_empty_middle_day(tmp_path)

    result, strategy = run_over_catalog(tmp_path)

    assert strategy.seen == [ts for day in FULL_DAYS for ts in hours(day)]
    assert result.backtest_end == hours(2)[-1]
