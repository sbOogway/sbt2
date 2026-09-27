import pytest
from kit import (
    HOUR,
    START,
    VENUE,
    BuyOneOnFirstQuote,
    mark,
    quote,
    run_engine,
    usdt,
)
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.model import Money, PortfolioSnapshot
from nautilus_trader.portfolio import PortfolioConfig
from nautilus_trader.trading import Strategy

pytestmark = pytest.mark.characterization

LAST_HOUR = 50
HOURLY = 3_600_000
RISING_MARKET = [
    tick
    for hour in range(LAST_HOUR + 1)
    for tick in (
        quote(START + hour * HOUR),
        mark(START + hour * HOUR, f"{50000 + hour * 10}.0"),
    )
]


class Idle(Strategy):
    pass


def snapshots(engine: BacktestEngine) -> list[PortfolioSnapshot]:
    account_id = engine.cache.account_id(VENUE)
    assert account_id is not None
    return engine.portfolio.snapshots(account_id)


def snapshot_hours(engine: BacktestEngine) -> list[int]:
    return [(snapshot.ts_event - START) // HOUR for snapshot in snapshots(engine)]


def final_equity(engine: BacktestEngine) -> Money:
    [equity] = snapshots(engine)[-1].total_equity
    return equity


def test_default_equity_curve_snapshots_start_each_utc_midnight_and_end() -> None:
    engine = run_engine(RISING_MARKET, BuyOneOnFirstQuote())

    assert snapshot_hours(engine) == [0, 24, 48, LAST_HOUR]
    assert final_equity(engine) == usdt("10500.00")


def test_disabled_equity_curve_takes_no_snapshots() -> None:
    engine = run_engine(
        RISING_MARKET, BuyOneOnFirstQuote(), PortfolioConfig(equity_curve=False)
    )

    assert snapshots(engine) == []


def test_snapshot_interval_samples_while_a_position_is_open() -> None:
    portfolio = PortfolioConfig(equity_curve=False, snapshot_interval_ms=HOURLY)
    engine = run_engine(RISING_MARKET, BuyOneOnFirstQuote(), portfolio)

    assert snapshot_hours(engine) == list(range(1, LAST_HOUR + 1))
    assert final_equity(engine) == usdt("10500.00")


def test_snapshot_interval_takes_no_snapshots_while_flat() -> None:
    portfolio = PortfolioConfig(equity_curve=False, snapshot_interval_ms=HOURLY)
    engine = run_engine(RISING_MARKET, Idle(), portfolio)

    assert snapshots(engine) == []
