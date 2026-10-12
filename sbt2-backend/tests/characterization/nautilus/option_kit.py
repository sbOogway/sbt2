from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, override

from kit import DAY, HOUR, START, quiet_engine_config
from nautilus_trader.backtest import BacktestEngine
from nautilus_trader.common import TimeEvent
from nautilus_trader.execution import FixedFeeModel
from nautilus_trader.model import (
    AccountType,
    AggressorSide,
    CryptoOption,
    Currency,
    InstrumentId,
    Money,
    OmsType,
    OptionGreeks,
    OptionKind,
    OrderFilled,
    OrderRejected,
    OrderSide,
    Price,
    Quantity,
    QuoteTick,
    Symbol,
    TradeId,
    TradeTick,
    Venue,
)
from nautilus_trader.trading import Strategy

VENUE = Venue("DERIBIT")
BTC = Currency.from_str("BTC")
EXPIRY_HOUR = 48
EXPIRY = START + EXPIRY_HOUR * HOUR
STRIKE = Price.from_str("50000")
CALL_ID = InstrumentId.from_str("BTC-3JAN24-50000-C.DERIBIT")
PUT_ID = InstrumentId.from_str("BTC-3JAN24-50000-P.DERIBIT")
STARTING_BALANCE = "1 BTC"

_KINDS = {CALL_ID: OptionKind.CALL, PUT_ID: OptionKind.PUT}
_NO_MARGIN = (Decimal(0), Decimal(0))


def option(
    instrument_id: InstrumentId = CALL_ID,
    margins: tuple[Decimal, Decimal] = _NO_MARGIN,
) -> CryptoOption:
    """A Deribit-like inverse option on BTC, priced and settled in BTC, as the
    deribit source builds it; ``margins`` are its initial and maintenance rates."""
    margin_init, margin_maint = margins
    return CryptoOption(
        instrument_id,
        Symbol(instrument_id.symbol.value),
        BTC,
        BTC,
        BTC,
        True,
        _KINDS[instrument_id],
        STRIKE,
        START - DAY,
        EXPIRY,
        4,
        1,
        Price.from_str("0.0001"),
        Quantity.from_str("0.1"),
        START,
        START,
        multiplier=Quantity.from_str("1"),
        margin_init=margin_init,
        margin_maint=margin_maint,
    )


def at(hour: int) -> int:
    return START + hour * HOUR


def trade(hour: int, price: str) -> TradeTick:
    ts = at(hour)
    return TradeTick(
        CALL_ID,
        Price.from_str(price),
        Quantity.from_str("1.0"),
        AggressorSide.BUY,
        TradeId(str(ts)),
        ts,
        ts,
    )


def quote(
    instrument_id: InstrumentId, hour: int, bid_ask: tuple[str, str]
) -> QuoteTick:
    ts = at(hour)
    bid, ask = bid_ask
    size = Quantity.from_str("10.0")
    return QuoteTick(
        instrument_id, Price.from_str(bid), Price.from_str(ask), size, size, ts, ts
    )


def greeks(instrument_id: InstrumentId, hour: int, mark_iv: float) -> OptionGreeks:
    ts = at(hour)
    return OptionGreeks(
        instrument_id,
        0.3,
        0.0001,
        10.0,
        -50.0,
        mark_iv=mark_iv,
        underlying_price=45000.0,
        ts_event=ts,
        ts_init=ts,
    )


@dataclass(frozen=True)
class Market:
    """The venue and the instruments of a run."""

    instruments: Sequence[CryptoOption] = (option(),)
    trade_execution: bool = True
    fee_model: Any = field(
        default_factory=lambda: FixedFeeModel(Money.from_str("0 BTC"))
    )


DEFAULT_MARKET = Market()


@dataclass(frozen=True)
class Fill:
    hour: float
    side: OrderSide
    price: Price
    quantity: Quantity


@dataclass
class Record:
    fills: list[Fill] = field(default_factory=list)
    rejections: list[str] = field(default_factory=list)
    commissions: list[Money | None] = field(default_factory=list)


class TimedOrders(Strategy):
    """Sends a market order on the call at each hour of ``orders``, between data."""

    def __init__(self, orders: Mapping[int, tuple[OrderSide, str]]) -> None:
        super().__init__()
        self.orders = dict(orders)
        self.record = Record()

    def on_start(self) -> None:
        self.subscribe_trades(CALL_ID)
        for hour in self.orders:
            self.clock.set_time_alert_ns(f"order-{hour}", at(hour), callback=self._send)

    def _send(self, event: TimeEvent) -> None:
        side, quantity = self.orders[(event.ts_event - START) // HOUR]
        order = self.order_factory.market(CALL_ID, side, Quantity.from_str(quantity))
        self.submit_order(order)

    @override
    def on_order_filled(self, event: OrderFilled) -> None:
        hour = (event.ts_event - START) / HOUR
        fill = Fill(hour, event.order_side, event.last_px, event.last_qty)
        self.record.fills.append(fill)
        self.record.commissions.append(event.commission)

    @override
    def on_order_rejected(self, event: OrderRejected) -> None:
        self.record.rejections.append(event.reason)


def run_engine(
    data: Sequence[Any], strategy: Strategy, market: Market = DEFAULT_MARKET
) -> BacktestEngine:
    engine = BacktestEngine(quiet_engine_config())
    engine.add_venue(
        VENUE,
        OmsType.NETTING,
        AccountType.MARGIN,
        [Money.from_str(STARTING_BALANCE)],
        default_leverage=Decimal(1),
        fee_model=market.fee_model,
        trade_execution=market.trade_execution,
    )
    for instrument in market.instruments:
        engine.add_instrument(instrument)
    engine.add_data(data)
    engine.add_strategy(strategy)
    engine.run()
    return engine


def run_orders(
    data: Sequence[Any],
    orders: Mapping[int, tuple[OrderSide, str]],
    market: Market = DEFAULT_MARKET,
) -> tuple[BacktestEngine, Record]:
    strategy = TimedOrders(orders)
    return run_engine(data, strategy, market), strategy.record


def btc(amount: str) -> Money:
    return Money.from_str(f"{amount} BTC")
