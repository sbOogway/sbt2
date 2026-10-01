from collections.abc import Sequence
from decimal import Decimal
from typing import Any, override

import pytest
from kit import (
    HOUR,
    INSTRUMENT_ID,
    START,
    STARTING_BALANCE,
    VENUE,
    mark,
    perpetual,
    quiet_engine_config,
    quote,
    trade,
    zero_fee_model,
)
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.model import (
    AccountType,
    Money,
    OmsType,
    OrderSide,
    Quantity,
    TradeTick,
)
from nautilus_trader.portfolio import PortfolioConfig
from nautilus_trader.trading import Strategy

# A 1 BTC long bought at 50,000 on 10,000 USDT keeps 10 USDT of equity at
# 40,010, under its 25 USDT maintenance margin (0.5% of the entry notional at
# leverage 10).
PRICES = ("50000.0", "45000.0", "40010.0", "40010.0")


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


def falling_trades_and_marks() -> list[Any]:
    return [
        each
        for hour, price in enumerate(PRICES)
        for each in (
            trade(START + hour * HOUR, price),
            mark(START + hour * HOUR, price),
        )
    ]


def falling_quotes() -> list[Any]:
    return [quote(START + hour * HOUR + 1, price) for hour, price in enumerate(PRICES)]


def run_long_with_liquidation(data: Sequence[Any]) -> BacktestEngine:
    engine = BacktestEngine(quiet_engine_config(PortfolioConfig(use_mark_prices=True)))
    engine.add_venue(
        VENUE,
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money.from_str(STARTING_BALANCE)],
        default_leverage=Decimal(10),
        fee_model=zero_fee_model(),
        liquidation_enabled=True,
    )
    engine.add_instrument(perpetual())
    engine.add_data(list(data))
    engine.add_strategy(BuyOneOnFirstTrade())
    engine.run()
    return engine


@pytest.mark.characterization
@pytest.mark.integration
def test_liquidation_never_fires_without_quotes() -> None:
    engine = run_long_with_liquidation(falling_trades_and_marks())

    [position] = engine.cache.positions()
    assert position.is_open


@pytest.mark.characterization
@pytest.mark.integration
def test_liquidation_fires_on_quotes() -> None:
    engine = run_long_with_liquidation([*falling_trades_and_marks(), *falling_quotes()])

    [position] = engine.cache.positions()
    assert position.is_closed
