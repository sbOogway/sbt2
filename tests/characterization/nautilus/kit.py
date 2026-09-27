from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.common import LoggerConfig, LogLevel
from nautilus_trader.execution import FixedFeeModel
from nautilus_trader.model import (
    AccountType,
    CryptoPerpetual,
    Currency,
    FundingRateUpdate,
    InstrumentId,
    MarkPriceUpdate,
    Money,
    OmsType,
    OrderSide,
    PositionAdjustmentType,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    Venue,
)
from nautilus_trader.portfolio import PortfolioConfig
from nautilus_trader.trading import Strategy

HOUR = 3_600_000_000_000
DAY = 24 * HOUR
START = 1_704_067_200_000_000_000  # 2024-01-01T00:00:00Z

VENUE = Venue("BYBIT")
INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-PERP.BYBIT")
USDT = Currency.from_str("USDT")
BTC = Currency.from_str("BTC")
STARTING_BALANCE = "10000 USDT"
FUNDING_INTERVAL_MINUTES = 480
FUNDING_INTERVAL = FUNDING_INTERVAL_MINUTES * 60_000_000_000


def perpetual() -> CryptoPerpetual:
    return CryptoPerpetual(
        INSTRUMENT_ID,
        Symbol("BTCUSDT"),
        BTC,
        USDT,
        USDT,
        False,
        1,
        3,
        Price.from_str("0.1"),
        Quantity.from_str("0.001"),
        0,
        0,
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
    )


def quote(ts: int, price: str = "50000.0") -> QuoteTick:
    size = Quantity.from_str("10.000")
    return QuoteTick(
        INSTRUMENT_ID, Price.from_str(price), Price.from_str(price), size, size, ts, ts
    )


def mark(ts: int, price: str = "50000.0") -> MarkPriceUpdate:
    return MarkPriceUpdate(INSTRUMENT_ID, Price.from_str(price), ts, ts)


def funding(
    ts: int, interval: int | None = FUNDING_INTERVAL_MINUTES
) -> FundingRateUpdate:
    return FundingRateUpdate(
        INSTRUMENT_ID, Decimal("0.0001"), ts, ts, interval=interval
    )


def zero_fee_model() -> FixedFeeModel:
    return FixedFeeModel(Money.from_str("0 USDT"))


def quiet_engine_config(
    portfolio: PortfolioConfig | None = None,
) -> BacktestEngineConfig:
    return BacktestEngineConfig(
        logging=LoggerConfig(stdout_level=LogLevel.ERROR),
        portfolio=portfolio,
    )


class BuyOneOnFirstQuote(Strategy):
    def on_start(self) -> None:
        self.bought = False
        self.subscribe_quotes(INSTRUMENT_ID)

    def on_quote(self, quote: QuoteTick) -> None:
        if self.bought:
            return
        self.bought = True
        order = self.order_factory.market(
            INSTRUMENT_ID, OrderSide.BUY, Quantity.from_str("1.000")
        )
        self.submit_order(order)


def run_engine(
    data: Sequence[Any],
    strategy: Strategy,
    portfolio: PortfolioConfig | None = None,
) -> BacktestEngine:
    engine = BacktestEngine(quiet_engine_config(portfolio))
    engine.add_venue(
        VENUE,
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money.from_str(STARTING_BALANCE)],
        default_leverage=Decimal(10),
        fee_model=zero_fee_model(),
    )
    engine.add_instrument(perpetual())
    engine.add_data(data)
    engine.add_strategy(strategy)
    engine.run()
    return engine


def run_long_one_btc(
    data: Sequence[Any], portfolio: PortfolioConfig | None = None
) -> BacktestEngine:
    return run_engine(data, BuyOneOnFirstQuote(), portfolio)


def funding_payments(engine: BacktestEngine) -> list[Money]:
    return [
        adjustment.pnl_change
        for position in engine.cache.positions()
        for adjustment in position.adjustments()
        if adjustment.adjustment_type == PositionAdjustmentType.FUNDING
        and adjustment.pnl_change is not None
    ]


def usdt(amount: str) -> Money:
    return Money.from_str(f"{amount} USDT")
