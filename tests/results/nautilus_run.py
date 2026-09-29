from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from nautilus_trader.analysis import ReportProvider
from nautilus_trader.backtest import BacktestEngine, BacktestEngineConfig
from nautilus_trader.common import LoggerConfig, LogLevel
from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.execution import FixedFeeModel
from nautilus_trader.model import (
    AccountType,
    AssetClass,
    CryptoPerpetual,
    Currency,
    FundingRateUpdate,
    InstrumentClass,
    InstrumentId,
    MarkPriceUpdate,
    Money,
    OmsType,
    OrderSide,
    PortfolioSnapshot,
    PositionAdjusted,
    PositionAdjustmentType,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    Venue,
)
from nautilus_trader.trading import Strategy

from sbt2.assets import asset_profile
from sbt2.results import Reports
from sbt2.spec import FractionSplit, ResolvedRunSpec
from sbt2.strategy import StrategyRun

START = datetime(2024, 1, 1, tzinfo=UTC)
END = START + timedelta(days=1)
INSTRUMENT_ID = InstrumentId.from_str("BTCUSDT-LINEAR.BYBIT")
USDT = Currency.from_str("USDT")
FUNDING_INTERVAL_MINUTES = 480
BUY_PRICE, SELL_PRICE = "50000.0", "51000.0"


@dataclass(frozen=True)
class RunOutput:
    snapshots: Sequence[PortfolioSnapshot]
    carry: Sequence[PositionAdjusted]
    reports: Reports


def spec(end: datetime = END) -> ResolvedRunSpec:
    return ResolvedRunSpec(
        strategy=StrategyRun("toy:RoundTrip", [INSTRUMENT_ID], {"lots": 1}, START),
        asset=asset_profile(AssetClass.CRYPTOCURRENCY, InstrumentClass.SWAP),
        source="bybit",
        venue={"name": "BYBIT", "starting_balances": ["10000 USDT"]},
        data=[],
        equity_interval_ms=3_600_000,
        split=FractionSplit(validation=0.2, test=0.2),
        part="train",
        start=START,
        end=end,
    )


def round_trip_with_funding() -> RunOutput:
    """Long 1 BTC at 50000 from the start, paying one funding, sold at 51000.

    Fees are 1 USDT a fill and funding is 0.0001 of the mark notional, 5 USDT.
    """
    engine = _engine()
    engine.add_data(
        [
            *_prices(_at(hours=0), BUY_PRICE),
            FundingRateUpdate(
                INSTRUMENT_ID,
                Decimal("0.0001"),
                _at(hours=8),
                _at(hours=8),
                interval=FUNDING_INTERVAL_MINUTES,
            ),
            *_prices(_at(hours=12), SELL_PRICE),
            *_prices(_at(hours=24), SELL_PRICE),
        ]
    )
    engine.add_strategy(_RoundTrip())
    engine.run()
    return _output(engine)


class _RoundTrip(Strategy):
    def on_start(self) -> None:
        self.quotes = 0
        self.subscribe_quotes(INSTRUMENT_ID)

    def on_quote(self, quote: QuoteTick) -> None:
        self.quotes += 1
        side = {1: OrderSide.BUY, 2: OrderSide.SELL}.get(self.quotes)
        if side is not None:
            self.submit_order(
                self.order_factory.market(INSTRUMENT_ID, side, Quantity.from_str("1"))
            )


def _engine() -> BacktestEngine:
    engine = BacktestEngine(
        BacktestEngineConfig(
            logging=LoggerConfig(stdout_level=LogLevel.ERROR),
            portfolio=spec().asset.portfolio_config(3_600_000),
        )
    )
    engine.add_venue(
        Venue("BYBIT"),
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money.from_str("10000 USDT")],
        default_leverage=Decimal(10),
        fee_model=FixedFeeModel(Money.from_str("1 USDT")),
    )
    engine.add_instrument(_perpetual())
    return engine


def _perpetual() -> CryptoPerpetual:
    return CryptoPerpetual(
        INSTRUMENT_ID,
        Symbol("BTCUSDT"),
        Currency.from_str("BTC"),
        USDT,
        USDT,
        False,
        1,
        0,
        Price.from_str("0.1"),
        Quantity.from_str("1"),
        0,
        0,
        margin_init=Decimal("0.01"),
        margin_maint=Decimal("0.005"),
    )


def _prices(ts: int, price: str) -> list[QuoteTick | MarkPriceUpdate]:
    size = Quantity.from_str("10")
    px = Price.from_str(price)
    return [
        QuoteTick(INSTRUMENT_ID, px, px, size, size, ts, ts),
        MarkPriceUpdate(INSTRUMENT_ID, px, ts, ts),
    ]


def _at(hours: int) -> int:
    return dt_to_unix_nanos(START + timedelta(hours=hours))


def _output(engine: BacktestEngine) -> RunOutput:
    cache = engine.cache
    account = cache.account_for_venue(Venue("BYBIT"))
    assert account is not None
    return RunOutput(
        snapshots=engine.portfolio.snapshots(account.id),
        carry=[
            adjustment
            for position in cache.positions()
            for adjustment in position.adjustments()
            if adjustment.adjustment_type == PositionAdjustmentType.FUNDING
        ],
        reports=Reports(
            fills=ReportProvider.generate_fills_report(cache.orders()),
            positions=ReportProvider.generate_positions_report(cache.positions()),
            account=ReportProvider.generate_account_report(account),
            orders=ReportProvider.generate_orders_report(cache.orders()),
        ),
    )
