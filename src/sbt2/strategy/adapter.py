from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from nautilus_trader.model import (
    Bar,
    BarType,
    ClientOrderId,
    InstrumentId,
    Money,
    OrderFilled,
    OrderSide,
    Quantity,
)
from nautilus_trader.trading import ImportableStrategyConfig
from nautilus_trader.trading import Strategy as NautilusStrategy

from sbt2.strategy.api import Fill, State, Strategy, import_strategy, resolve_params
from sbt2.strategy.reconciler import (
    Cancel,
    OrderAction,
    PlaceMarket,
    WorkingOrder,
    reconcile,
)


@dataclass(frozen=True)
class AdapterConfig:
    """What the adapter runs: a strategy import path, its instruments and parameters.

    ``trade_start`` is the segment start; before it the strategy only warms up.
    """

    strategy: str
    instruments: Sequence[str]
    params: Mapping[str, Any]
    trade_start: datetime


@dataclass(frozen=True)
class _WireConfig:
    """``AdapterConfig`` as the JSON primitives nautilus passes through."""

    strategy: str
    instruments: list[str]
    params: dict[str, Any]
    trade_start: str


def importable_config(config: AdapterConfig) -> ImportableStrategyConfig:
    wire = _WireConfig(
        config.strategy,
        list(config.instruments),
        dict(config.params),
        config.trade_start.isoformat(),
    )
    return ImportableStrategyConfig(
        f"{__name__}:Adapter", f"{__name__}:_WireConfig", asdict(wire)
    )


class Adapter(NautilusStrategy):
    def __init__(self, config: _WireConfig) -> None:
        super().__init__(config)
        strategy = import_strategy(config.strategy)
        params = resolve_params(strategy, config.params)
        self._strategy: Strategy[Any] = strategy(params)
        self._instrument_ids = [
            InstrumentId.from_str(each) for each in config.instruments
        ]
        self._bar_types = [
            bars.bar_type(instrument_id)
            for instrument_id in self._instrument_ids
            for bars in strategy.inputs(params)
        ]
        self._trade_start_ns = _to_nanos(datetime.fromisoformat(config.trade_start))
        self._latest_bars: dict[BarType, Bar] = {}

    def on_start(self) -> None:
        for bar_type in self._bar_types:
            self.subscribe_bars(bar_type)

    def on_bar(self, bar: Bar) -> None:
        self._latest_bars[bar.bar_type] = bar
        intents = self._strategy.decide(self._state(bar.ts_event))
        if bar.ts_event < self._trade_start_ns:
            return
        for action in reconcile(intents, self._positions(), self._working_orders()):
            self._execute(action)

    def on_order_filled(self, event: OrderFilled) -> None:
        quantity = event.last_qty.as_decimal()
        signed = quantity if event.order_side == OrderSide.BUY else -quantity
        fill = Fill(
            event.instrument_id,
            signed,
            event.last_px.as_decimal(),
            _to_datetime(event.ts_event),
        )
        self._strategy.on_fill(fill)

    def _state(self, ts: int) -> State:
        return State(
            _to_datetime(ts),
            dict(self._latest_bars),
            self._positions(),
            self._equity(),
        )

    def _positions(self) -> dict[InstrumentId, Decimal]:
        return {
            instrument_id: self.portfolio.net_position(instrument_id)
            for instrument_id in self._instrument_ids
        }

    def _equity(self) -> Money:
        venue = self._instrument_ids[0].venue
        [equity] = self.portfolio.equity(venue).values()
        return equity

    def _working_orders(self) -> list[WorkingOrder]:
        orders = self.cache.orders_open(strategy_id=self.strategy_id)
        orders += self.cache.orders_inflight(strategy_id=self.strategy_id)
        return [_working_order(order) for order in orders]

    def _execute(self, action: OrderAction) -> None:
        match action:
            case PlaceMarket():
                self._place_market(action)
            case Cancel():
                self.cancel_order(ClientOrderId(action.order_id))

    def _place_market(self, action: PlaceMarket) -> None:
        quantity = self._tradable_quantity(action.instrument_id, abs(action.quantity))
        if not quantity:
            return
        side = OrderSide.BUY if action.quantity > 0 else OrderSide.SELL
        order = self.order_factory.market(
            action.instrument_id, side, Quantity.from_str(str(quantity))
        )
        self.submit_order(order)

    def _tradable_quantity(
        self, instrument_id: InstrumentId, quantity: Decimal
    ) -> Decimal:
        instrument = self.cache.instrument(instrument_id)
        if instrument is None:
            raise LookupError(f"instrument {instrument_id} is not loaded")
        increment = instrument.size_increment.as_decimal()
        return quantity // increment * increment


def _working_order(order: Any) -> WorkingOrder:
    leaves = order.leaves_qty.as_decimal()
    signed = leaves if order.side == OrderSide.BUY else -leaves
    return WorkingOrder(str(order.client_order_id), order.instrument_id, signed)


def _to_nanos(moment: datetime) -> int:
    since_epoch = moment - datetime(1970, 1, 1, tzinfo=UTC)
    return since_epoch // timedelta(microseconds=1) * 1_000


def _to_datetime(nanos: int) -> datetime:
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(microseconds=nanos // 1_000)
