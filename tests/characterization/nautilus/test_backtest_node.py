from decimal import Decimal
from pathlib import Path

import pytest
from catalog_kit import day_bounds, new_catalog, write_funding
from kit import (
    FUNDING_INTERVAL,
    HOUR,
    INSTRUMENT_ID,
    START,
    STARTING_BALANCE,
    VENUE,
    BuyOneOnFirstQuote,
    funding,
    funding_payments,
    mark,
    perpetual,
    quiet_engine_config,
    quote,
    usdt,
    zero_fee_model,
)
from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestNode,
    BacktestResult,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.common import LoggerConfig, LogLevel
from nautilus_trader.model import NautilusDataType, QuoteTick
from nautilus_trader.trading import Strategy

pytestmark = pytest.mark.characterization

STREAMED_TYPES = [
    NautilusDataType.QuoteTick,
    NautilusDataType.MarkPriceUpdate,
    NautilusDataType.FundingRateUpdate,
]


def build_one_day_catalog(path: Path) -> None:
    start, end = day_bounds(0)
    catalog = new_catalog(path)
    catalog.write_instruments([perpetual()])
    catalog.write_quote_ticks([quote(ts) for ts in range(start, end, HOUR)], start, end)
    catalog.write_mark_price_updates(
        [mark(ts) for ts in range(start, end, HOUR)], start, end
    )
    fundings = [funding(START + k * FUNDING_INTERVAL) for k in (1, 2)]
    write_funding(path, fundings, (start, end))


def venues() -> list[BacktestVenueConfig]:
    venue = BacktestVenueConfig(
        VENUE.value,
        "NETTING",
        "MARGIN",
        [STARTING_BALANCE],
        default_leverage=Decimal(10),
        fee_model=zero_fee_model(),
    )
    return [venue]


def catalog_streams(path: Path) -> list[BacktestDataConfig]:
    return [
        BacktestDataConfig(data_type, str(path), instrument_id=INSTRUMENT_ID)
        for data_type in STREAMED_TYPES
    ]


def default_run_config(path: Path) -> BacktestRunConfig:
    return BacktestRunConfig(
        venues(), catalog_streams(path), engine=quiet_engine_config()
    )


def undisposed_run_config(path: Path) -> BacktestRunConfig:
    return BacktestRunConfig(
        venues(),
        catalog_streams(path),
        engine=quiet_engine_config(),
        dispose_on_completion=False,
    )


def run_node(config: BacktestRunConfig) -> BacktestNode:
    node = BacktestNode([config])
    node.build()
    node.add_strategy(config.id, BuyOneOnFirstQuote())
    node.run()
    return node


@pytest.fixture
def finished_node(tmp_path: Path) -> tuple[BacktestNode, str]:
    build_one_day_catalog(tmp_path)
    config = undisposed_run_config(tmp_path)
    return run_node(config), config.id


def test_node_streams_catalog_funding_and_the_venue_settles_it(
    finished_node: tuple[BacktestNode, str],
) -> None:
    node, run_id = finished_node

    assert funding_payments(node.get_engine_cache(run_id)) == [usdt("-5.00")] * 2


def test_portfolio_snapshots_survive_the_run_without_disposal(
    finished_node: tuple[BacktestNode, str],
) -> None:
    node, run_id = finished_node
    cache = node.get_engine_cache(run_id)
    account_id = cache.account_id(VENUE)
    assert account_id is not None

    [equity] = node.get_engine_portfolio(run_id).snapshots(account_id)[-1].total_equity
    assert equity == usdt("9990.00")


def test_default_disposal_silently_empties_the_engine_cache(tmp_path: Path) -> None:
    build_one_day_catalog(tmp_path)
    config = default_run_config(tmp_path)
    cache = run_node(config).get_engine_cache(config.id)

    assert cache.account_id(VENUE) is None
    assert funding_payments(cache) == []


class FailOnQuote(Strategy):
    def on_start(self) -> None:
        self.subscribe_quotes(INSTRUMENT_ID)

    def on_quote(self, quote: QuoteTick) -> None:
        raise RuntimeError("strategy failed")


def failing_run(path: Path, shutdown_on_error: bool) -> BacktestResult:
    build_one_day_catalog(path)
    start, end = day_bounds(0)
    config = BacktestRunConfig(
        venues(),
        catalog_streams(path),
        engine=BacktestEngineConfig(
            logging=LoggerConfig(stdout_level=LogLevel.ERROR),
            shutdown_on_error=shutdown_on_error,
        ),
        raise_exception=True,
        start=start,
        end=end,
    )
    node = BacktestNode([config])
    node.build()
    node.add_strategy(config.id, FailOnQuote())
    [result] = node.run()
    return result


def test_strategy_errors_are_logged_not_raised_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    result = failing_run(tmp_path, shutdown_on_error=False)

    assert result.backtest_end == START + 23 * HOUR


def test_shutdown_on_error_stops_the_run_early_without_raising(
    tmp_path: Path,
) -> None:
    result = failing_run(tmp_path, shutdown_on_error=True)

    assert result.backtest_end == START
