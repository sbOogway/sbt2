import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from nautilus_trader.analysis import ReportProvider
from nautilus_trader.backtest import BacktestDataConfig, BacktestNode, BacktestRunConfig
from nautilus_trader.common import Cache, LoggerConfig, LogLevel
from nautilus_trader.model import PositionAdjusted, PositionAdjustmentType, Venue

from sbt2.core.assets import MarginModel
from sbt2.core.results import OutputSink, Reports
from sbt2.core.spec import ResolvedRunSpec
from sbt2.core.strategy import (
    Strategy,
    StrategyRun,
    build_strategy,
    strategy_source,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunSettings:
    """Machine settings, which never change a run's results.

    ``log_level`` is nautilus's own stdout level. Nautilus sets its logger up
    once per process, so only the first run in a process applies it.
    """

    catalog: Path
    chunk_size: int = 100_000
    log_level: LogLevel = LogLevel.INFO


class BacktestError(RuntimeError):
    pass


class NoAccountError(BacktestError):
    pass


@dataclass(frozen=True)
class _Backtest:
    node: BacktestNode
    config_id: str
    venue: Venue
    margin: MarginModel | None


@dataclass(frozen=True)
class _Plan:
    config: BacktestRunConfig
    margin: MarginModel | None


def execute(spec: ResolvedRunSpec, sink: OutputSink, settings: RunSettings) -> None:
    """Run one backtest in this process and hand its output to ``sink``."""
    logger.info("run %s: %s from %s", sink.run_id, spec.strategy.strategy, spec.start)
    sink.write_strategy_source(strategy_source(spec.strategy.strategy))
    with TemporaryDirectory(prefix="sbt2-quotes-") as folder:
        quotes = spec.asset.quotes.write(spec.quote_job(settings.catalog), Path(folder))
        margin = spec.asset.margin.model(spec.quote_job(settings.catalog))
        _execute(spec, sink, _Plan(_run_config(spec, settings, quotes), margin))
    sink.finalize()
    logger.info("run %s finished", sink.run_id)


def _execute(spec: ResolvedRunSpec, sink: OutputSink, plan: _Plan) -> None:
    node = BacktestNode([plan.config])
    backtest = _Backtest(node, plan.config.id, Venue(spec.venue_name), plan.margin)
    try:
        strategy = _run(backtest, spec.strategy)
        _write_output(backtest, spec, sink)
        _write_drawdown_trip(strategy, sink)
    finally:
        backtest.node.dispose()


def _run_config(
    spec: ResolvedRunSpec, settings: RunSettings, quotes: Sequence[BacktestDataConfig]
) -> BacktestRunConfig:
    engine = {
        "logging": LoggerConfig(stdout_level=settings.log_level),
        "shutdown_on_error": True,
        "run_analysis": False,
    }
    return spec.run_config(
        str(settings.catalog),
        engine,
        quotes,
        chunk_size=settings.chunk_size,
        raise_exception=True,
        dispose_on_completion=False,
    )


def _run(backtest: _Backtest, run: StrategyRun) -> Strategy[Any]:
    try:
        strategy = build_strategy(run)
        if backtest.margin is not None:
            strategy.use_margin(backtest.margin)
        backtest.node.build()
        backtest.node.add_strategy(backtest.config_id, strategy)
        backtest.node.run()
    except Exception as error:
        raise BacktestError(f"backtest of {run.strategy} failed: {error}") from error
    if strategy.failure is not None:
        raise BacktestError(
            f"strategy {run.strategy} failed: {strategy.failure!r}"
        ) from strategy.failure
    return strategy


def _write_output(backtest: _Backtest, spec: ResolvedRunSpec, sink: OutputSink) -> None:
    cache = backtest.node.get_engine_cache(backtest.config_id)
    account = cache.account_for_venue(backtest.venue)
    if account is None:
        raise NoAccountError(f"the run opened no account on {backtest.venue}")
    portfolio = backtest.node.get_engine_portfolio(backtest.config_id)
    sink.write_equity(
        portfolio.snapshots(account.id), spec.asset.equity.corrections(cache)
    )
    sink.write_carry(_funding(cache))
    sink.write_reports(_reports(cache, account))


def _write_drawdown_trip(strategy: Strategy[Any], sink: OutputSink) -> None:
    if strategy.drawdown_tripped_at is not None:
        sink.write_drawdown_trip(strategy.drawdown_tripped_at)


def _reports(cache: Cache, account: Any) -> Reports:
    return Reports(
        fills=ReportProvider.generate_fills_report(cache.orders()),
        positions=ReportProvider.generate_positions_report(
            cache.positions(), cache.position_snapshots()
        ),
        account=ReportProvider.generate_account_report(account),
        orders=ReportProvider.generate_orders_report(cache.orders()),
    )


def _funding(cache: Cache) -> list[PositionAdjusted]:
    """Reversing a netting position moves its earlier adjustments to a snapshot."""
    positions = [*cache.position_snapshots(), *cache.positions()]
    return [
        adjustment
        for position in positions
        for adjustment in position.adjustments()
        if adjustment.adjustment_type == PositionAdjustmentType.FUNDING
    ]
