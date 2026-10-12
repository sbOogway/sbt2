from collections.abc import Mapping
from typing import override

import pytest
from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.common import LoggerConfig, LogLevel, TimeEvent
from nautilus_trader.execution import FixedFeeModel
from nautilus_trader.model import (
    AccountType,
    AggressorSide,
    AssetClass,
    InstrumentClass,
    MarkPriceUpdate,
    Money,
    OmsType,
    OrderSide,
    Price,
    Quantity,
    TradeId,
    TradeTick,
    Venue,
)
from nautilus_trader.portfolio import PortfolioConfig
from nautilus_trader.trading import Strategy
from option_catalog import OPTION_ID, START, option

from sbt2.core.assets import asset_profile

HOUR = 3_600_000_000_000
START_NS = int(START.timestamp()) * 1_000_000_000
LAST_HOUR = 10
MARK = 0.08
VENUE = Venue("DERIBIT")
Orders = Mapping[int, tuple[OrderSide, str]]


def at(hour: int) -> int:
    return START_NS + hour * HOUR


class TimedOrders(Strategy):
    def __init__(self, orders: Orders) -> None:
        super().__init__()
        self.orders = dict(orders)

    @override
    def on_start(self) -> None:
        self.subscribe_trades(OPTION_ID)
        for hour in self.orders:
            self.clock.set_time_alert_ns(f"order-{hour}", at(hour), self._send)

    def _send(self, event: TimeEvent) -> None:
        side, quantity = self.orders[(event.ts_event - START_NS) // HOUR]
        self.submit_order(
            self.order_factory.market(OPTION_ID, side, Quantity.from_str(quantity))
        )


def trade(hour: int, price: str) -> TradeTick:
    ts = at(hour)
    return TradeTick(
        OPTION_ID,
        Price.from_str(price),
        Quantity.from_str("10.0"),
        AggressorSide.BUY,
        TradeId(str(ts)),
        ts,
        ts,
    )


def mark(hour: int) -> MarkPriceUpdate:
    return MarkPriceUpdate(OPTION_ID, Price(MARK, 4), at(hour), at(hour))


def run(orders: Orders) -> BacktestEngine:
    config = BacktestEngineConfig(
        logging=LoggerConfig(stdout_level=LogLevel.ERROR),
        portfolio=PortfolioConfig(use_mark_prices=True, snapshot_interval_ms=3_600_000),
    )
    engine = BacktestEngine(config)
    engine.add_venue(
        VENUE,
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money.from_str("1 BTC")],
        fee_model=FixedFeeModel(Money.from_str("0 BTC")),
    )
    engine.add_instrument(option())
    engine.add_data(
        [trade(0, "0.0500"), trade(4, "0.0700"), *map(mark, range(LAST_HOUR + 1))]
    )
    engine.add_strategy(TimedOrders(orders))
    engine.run()
    return engine


def corrected_equity(engine: BacktestEngine) -> float:
    """The equity of the last snapshot plus the correction of the last fill."""
    account_id = engine.cache.account_id(VENUE)
    assert account_id is not None
    [equity] = engine.portfolio.snapshots(account_id)[-1].total_equity
    equity_convention = asset_profile(
        AssetClass.CRYPTOCURRENCY, InstrumentClass.OPTION
    ).equity
    corrections = equity_convention.corrections(engine.cache)
    return equity.as_double() + corrections["amount"].iloc[-1]


def cash_and_position(engine: BacktestEngine) -> float:
    """The balance plus the open contracts at the mark: the true equity."""
    account = engine.cache.account_for_venue(VENUE)
    assert account is not None
    [position] = engine.cache.positions()
    balance = account.balance_total(position.settlement_currency)
    assert balance is not None
    return balance.as_double() + position.signed_qty * MARK


@pytest.mark.integration
def test_a_partial_close_keeps_the_average_cost_of_the_rest() -> None:
    engine = run({2: (OrderSide.BUY, "2.0"), 6: (OrderSide.SELL, "1.0")})

    assert corrected_equity(engine) == pytest.approx(1 - 0.10 + 0.07 + 0.08)
    assert corrected_equity(engine) == pytest.approx(cash_and_position(engine))


@pytest.mark.integration
def test_a_reversal_starts_the_cost_again_at_the_fill_price() -> None:
    engine = run({2: (OrderSide.BUY, "1.0"), 6: (OrderSide.SELL, "2.0")})

    assert corrected_equity(engine) == pytest.approx(1 - 0.05 + 0.14 - 0.08)
    assert corrected_equity(engine) == pytest.approx(cash_and_position(engine))
