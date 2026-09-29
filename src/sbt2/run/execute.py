import copyreg
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nautilus_trader.analysis import ReportProvider
from nautilus_trader.backtest import BacktestNode, BacktestRunConfig
from nautilus_trader.common import Cache, LoggerConfig, LogLevel
from nautilus_trader.model import PositionAdjusted, PositionAdjustmentType, Venue

from sbt2.results import OutputSink, Reports
from sbt2.spec import ResolvedRunSpec
from sbt2.strategy import StrategyRun, build_strategy

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


def _level_by_name(level: LogLevel) -> tuple[Callable[..., LogLevel], tuple[str]]:
    """Nautilus's enums don't pickle; a level comes back by its name."""
    return LogLevel.from_str, (level.name,)


copyreg.pickle(LogLevel, _level_by_name)


class BacktestError(RuntimeError):
    pass


class NoAccountError(BacktestError):
    pass


@dataclass(frozen=True)
class _Backtest:
    node: BacktestNode
    config_id: str
    venue: Venue


def execute(spec: ResolvedRunSpec, sink: OutputSink, settings: RunSettings) -> None:
    """Run one backtest in this process and hand its output to ``sink``."""
    logger.info("run %s: %s from %s", sink.run_id, spec.strategy.strategy, spec.start)
    config = _run_config(spec, settings)
    backtest = _Backtest(BacktestNode([config]), config.id, Venue(spec.venue["name"]))
    try:
        _run(backtest, spec.strategy)
        _write_output(backtest, sink)
    finally:
        backtest.node.dispose()
    sink.finalize()
    logger.info("run %s finished", sink.run_id)


def _run_config(spec: ResolvedRunSpec, settings: RunSettings) -> BacktestRunConfig:
    engine = {
        "logging": LoggerConfig(stdout_level=settings.log_level),
        "shutdown_on_error": True,
        "run_analysis": False,
    }
    return spec.run_config(
        str(settings.catalog),
        engine,
        chunk_size=settings.chunk_size,
        raise_exception=True,
        dispose_on_completion=False,
    )


def _run(backtest: _Backtest, run: StrategyRun) -> None:
    try:
        strategy = build_strategy(run)
        backtest.node.build()
        backtest.node.add_strategy(backtest.config_id, strategy)
        backtest.node.run()
    except Exception as error:
        raise BacktestError(f"backtest of {run.strategy} failed: {error}") from error
    if strategy.failure is not None:
        raise BacktestError(
            f"strategy {run.strategy} failed: {strategy.failure!r}"
        ) from strategy.failure


def _write_output(backtest: _Backtest, sink: OutputSink) -> None:
    cache = backtest.node.get_engine_cache(backtest.config_id)
    account = cache.account_for_venue(backtest.venue)
    if account is None:
        raise NoAccountError(f"the run opened no account on {backtest.venue}")
    portfolio = backtest.node.get_engine_portfolio(backtest.config_id)
    sink.write_equity(portfolio.snapshots(account.id))
    sink.write_carry(_funding(cache))
    sink.write_reports(_reports(cache, account))


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
    funding = [
        adjustment
        for position in positions
        for adjustment in position.adjustments()
        if adjustment.adjustment_type == PositionAdjustmentType.FUNDING
    ]
    return sorted(funding, key=lambda adjustment: adjustment.ts_event)
