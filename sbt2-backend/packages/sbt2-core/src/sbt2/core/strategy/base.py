import functools
import hashlib
import importlib
import importlib.util
import inspect
import logging
import sys
import threading
import weakref
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    get_args,
    get_origin,
    get_type_hints,
)

from nautilus_trader.common import TimeEvent
from nautilus_trader.core import dt_to_unix_nanos, unix_nanos_to_dt
from nautilus_trader.model import (
    AggregationSource,
    Bar,
    BarSpecification,
    BarType,
    ClientOrderId,
    IndexPriceUpdate,
    InstrumentId,
    OptionGreeks,
    OrderDenied,
    OrderFilled,
    OrderRejected,
    OrderSide,
    Quantity,
)
from nautilus_trader.trading import ImportableStrategyConfig
from nautilus_trader.trading import Strategy as NautilusStrategy

from sbt2.core.market import ChainFeeds
from sbt2.core.strategy.book_rules import BookRules
from sbt2.core.strategy.chain import CachedChain, Chain, NoMarketError
from sbt2.core.strategy.chain_records import ChainHistory
from sbt2.core.strategy.combo import Combo, ComboExit, Leg
from sbt2.core.strategy.combo_book import Change, ComboBook, combo_tag
from sbt2.core.strategy.conversion import Conversion
from sbt2.core.strategy.drawdown import DrawdownGuard
from sbt2.core.strategy.expiry import SETTLEMENT_TAG, closing_side, settlement_time
from sbt2.core.strategy.margin import MarginDesk, MarginModel
from sbt2.core.strategy.markets import Markets
from sbt2.core.strategy.portfolio_greeks import GreeksDesk, GreeksSample
from sbt2.core.strategy.schema import is_str_tuple
from sbt2.core.strategy.short_premium import ShortPremiumRules
from sbt2.data import candle_type

if TYPE_CHECKING:
    from sbt2.core.results import Benchmark

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Refusal:
    """A combo the short premium rules refused: ``ts_event`` (ns), the
    instrument ids of its legs and the ``reason``."""

    ts_event: int
    legs: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class NoParams:
    pass


@dataclass(frozen=True)
class StrategyRun:
    """What to run: a strategy import path, its instruments and parameters.

    ``trade_start`` is the segment start; before it the strategy only warms up.
    ``aggregated_from`` names the external bars the declared bars are built
    from, such as ``"1-MINUTE-EXTERNAL"``; ``None`` builds them from trades.
    ``drawdown_limit`` is the fraction of peak equity the run may lose.
    ``feeds`` name the index and the volatility index of each chain a run
    streams; the strategy hears their prices and the IV of its contracts.
    ``short_premium`` turns the portfolio rules of a short premium book on.
    ``currency`` is the reporting currency the portfolio greeks are in, the
    underlying of the first chain by default, and ``lookback`` is how far back
    the betas of the underlyings to BTC look.
    """

    strategy: str
    instruments: Sequence[InstrumentId]
    params: Mapping[str, Any]
    trade_start: datetime
    aggregated_from: str | None = None
    drawdown_limit: Decimal | None = None
    feeds: Sequence[ChainFeeds] = ()
    short_premium: ShortPremiumRules | None = None
    currency: str | None = None
    lookback: timedelta = timedelta(0)


@dataclass(frozen=True)
class RunConfig:
    """``StrategyRun`` as the JSON primitives nautilus passes to the strategy."""

    instruments: list[str]
    params: dict[str, Any]
    trade_start: str
    aggregated_from: str | None = None
    drawdown_limit: str | None = None
    feeds: list[dict[str, str]] | None = None
    short_premium: dict[str, Any] | None = None
    currency: str | None = None
    lookback_seconds: float = 0.0


def importable_config(run: StrategyRun) -> ImportableStrategyConfig:
    return ImportableStrategyConfig(
        run.strategy, f"{__name__}:RunConfig", asdict(_run_config(run))
    )


def build_strategy(run: StrategyRun) -> Strategy[Any]:
    return import_strategy(run.strategy)(_run_config(run))


def _run_config(run: StrategyRun) -> RunConfig:
    return RunConfig(
        [str(each) for each in run.instruments],
        dict(run.params),
        run.trade_start.isoformat(),
        run.aggregated_from,
        None if run.drawdown_limit is None else str(run.drawdown_limit),
        [_feed_primitives(each) for each in run.feeds] or None,
        None if run.short_premium is None else run.short_premium.as_primitives(),
        run.currency,
        run.lookback.total_seconds(),
    )


def _feed_primitives(feeds: ChainFeeds) -> dict[str, str]:
    return {
        "underlying": feeds.underlying,
        "index": str(feeds.index),
        "volatility": str(feeds.volatility),
    }


def _feeds_of(table: dict[str, str]) -> ChainFeeds:
    return ChainFeeds(
        table["underlying"],
        InstrumentId.from_str(table["index"]),
        InstrumentId.from_str(table["volatility"]),
    )


_GREEKS_INTERVAL = timedelta(hours=1)


def _recording_failure(handler: Callable[..., Any]) -> Callable[..., Any]:
    """Nautilus logs a handler's exception and never raises it out of the run."""

    @functools.wraps(handler)
    def recorded(self: Strategy[Any], *args: Any, **kwargs: Any) -> Any:
        try:
            return handler(self, *args, **kwargs)
        except BaseException as error:
            if self.failure is None:
                self.failure = error
            raise

    return recorded


class Strategy[P](NautilusStrategy, ABC):
    """A nautilus strategy that sbt2 can describe without running it.

    ``Params`` is a dataclass: its fields are the parameter schema and defaults.
    ``benchmark`` is the default benchmark reports compare the strategy against;
    ``None`` compares it against nothing.
    ``inputs`` declares the bars the strategy needs; they are aggregated at run
    time from trades or 1-minute candles and subscribed on start, so a subclass
    that overrides ``on_start`` calls ``super().on_start()``. Either way they
    arrive under the types ``bar_types`` gives. Orders submitted while
    ``warming_up`` are dropped. The first exception raised by a subclass's
    ``on_*`` handler is kept in ``failure``.

    A strategy that needs no bars, such as one that picks contracts of an option
    chain, declares no ``inputs`` and acts on a ``schedule``: ``on_schedule`` is
    called at that interval, from the start of the run. It reads the IV, the
    greeks and the IV rank of the contracts through ``chain``; a strategy that
    reads the IV rank sets ``iv_lookback`` to load the DVOL before the run.

    A position in an option is closed at the contract's expiry, after its open
    orders are cancelled, and ``on_settlement`` hears the closing fill; a
    subclass that overrides ``on_order_filled`` need not call ``super()``.

    A multi-leg trade is a ``Combo``: ``open_combo`` sends its legs together and
    ``close_combo`` closes them together. ``combos`` lists the open ones, and a
    ``combo_exit`` rule closes them at a DTE or a target. Each order of a combo
    carries its id in its tags, as ``COMBO:<id>``.

    With a drawdown limit, each bar after warm-up first checks total equity
    against its peak; once it falls the limit or more below, the strategy
    exits the market, records the bar's time in ``drawdown_tripped_at`` and
    drops every order after.
    """

    Params: ClassVar[type[Any]] = NoParams
    benchmark: ClassVar[Benchmark | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for name, hearing in _HEARING.items():
            if name in vars(cls):
                setattr(cls, name, hearing(vars(cls)[name]))
        for name, handler in list(vars(cls).items()):
            if name.startswith("on_") and callable(handler):
                setattr(cls, name, _recording_failure(handler))

    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        self.failure: BaseException | None = None
        self.params: P = resolve_params(type(self), config.params)
        self.instrument_ids = [
            InstrumentId.from_str(each) for each in config.instruments
        ]
        self._trade_start_ns = dt_to_unix_nanos(config.trade_start)
        self._aggregated_from = config.aggregated_from
        self.drawdown_tripped_at: datetime | None = None
        self._settling: set[ClientOrderId] = set()
        self._combos = ComboBook()
        self._margin: MarginDesk | None = None
        self._short_premium = (
            None
            if config.short_premium is None
            else ShortPremiumRules.from_primitives(config.short_premium)
        )
        weak = weakref.proxy(self)
        self._markets = Markets(
            [_feeds_of(each) for each in config.feeds or []],
            lambda: weak.clock.timestamp_ns(),
            timedelta(seconds=config.lookback_seconds),
        )
        self._rules = (
            None
            if self._short_premium is None
            else BookRules(self._short_premium, weak, Conversion(self._markets.prices))
        )
        self.refusals: list[Refusal] = []
        self.portfolio_greeks: list[GreeksSample] = []
        self._greeks = (
            None
            if not self._markets.feeds
            else GreeksDesk(weak, self._markets, config.currency)
        )
        self._drawdown = (
            None
            if config.drawdown_limit is None
            else DrawdownGuard(Decimal(config.drawdown_limit))
        )

    @classmethod
    def warmup(cls, _params: P, /) -> timedelta:
        return timedelta(0)

    @classmethod
    def iv_lookback(cls, _params: P, /) -> timedelta:
        """How far before the run's data the volatility index is loaded, for
        ``chain.iv_rank`` and ``chain.iv_percentile``; return ``IV_LOOKBACK`` or
        more to read them."""
        return timedelta(0)

    @classmethod
    @abstractmethod
    def inputs(cls, params: P) -> Sequence[BarSpecification]: ...

    @classmethod
    def feeds(cls, _params: P, /) -> Sequence[InstrumentId]:
        """The instruments, on other venues, whose 1-minute candles the run
        streams besides the traded ones; the strategy hears them in ``on_bar``
        and the run never trades them."""
        return ()

    @classmethod
    def combo_exit(cls, _params: P, /) -> ComboExit | None:
        """When to close the open combos, checked at each ``schedule`` tick before
        ``on_schedule``; ``None`` closes none."""
        return None

    @classmethod
    def schedule(cls, _params: P, /) -> timedelta | None:
        """How often ``on_schedule`` is called; ``None`` for never."""
        return None

    @property
    def chain(self) -> Chain:
        """The option contracts the run loaded, to pick from; a run that streams
        several chains has to ask ``chains`` for one."""
        return CachedChain(self.cache, self.instrument_ids, self._markets.only())

    @property
    def chains(self) -> dict[str, Chain]:
        """The option chain of each underlying the run streams, by its code, such
        as ``"BTC"``; each ranks the IV on its own volatility index."""
        return dict(self._markets.chains(self.cache, self.instrument_ids))

    def equity(self, currency: str) -> Decimal:
        """All run balances in ``currency``, at the latest index prices."""
        conversion = Conversion(self._markets.prices)
        accounts = [
            self.portfolio.account(venue)
            for venue in {each.venue for each in self.instrument_ids}
        ]
        return sum(
            (
                conversion.balances(account, currency)
                for account in accounts
                if account is not None
            ),
            Decimal(0),
        )

    def index_correlation(self) -> dict[str, dict[str, float]]:
        """Daily index return correlations over the run's look-back; 1 on the
        diagonal and for pairs with fewer than five common returns."""
        return self._markets.index_correlation()

    @property
    def short_premium_rules(self) -> ShortPremiumRules | None:
        """The rules of the spec's ``[risk.short_premium]`` table, which
        ``open_combo`` applies; ``None`` when the table is absent."""
        return self._short_premium

    @property
    def warming_up(self) -> bool:
        return self.clock.timestamp_ns() < self._trade_start_ns

    def bar_types(self) -> list[BarType]:
        return [
            BarType(instrument_id, spec, AggregationSource.INTERNAL)
            for instrument_id in self.instrument_ids
            for spec in self.inputs(self.params)
        ]

    def on_start(self) -> None:
        for bar_type in self.bar_types():
            self.subscribe_bars(self._subscribed(bar_type))
        for feed in self.feeds(self.params):
            self.subscribe_bars(candle_type(feed))
        self._listen_to_market()
        self._arm_settlement()
        self._arm_schedule()
        self._arm_greeks()

    @property
    def combos(self) -> tuple[Combo, ...]:
        """The combos that are open: every leg is filled, none is closed yet."""
        return self._combos.opened()

    def open_combo(self, combo: Combo) -> Combo:
        """Send the legs of ``combo`` as one list of market orders and return the
        combo with its id, which the order tags and the fills carry. The free
        equity must cover the margin of the whole list, else no leg is sent and
        ``on_margin_refused`` is called. With the short premium rules on, a combo
        that breaks one is not sent either: ``on_combo_refused`` is called and the
        combo comes back with no id. ``on_combo_opened`` is called once every
        leg is filled; a leg the venue refuses closes the legs that filled, at once, calls
        ``on_combo_failed`` and the combo is never open."""
        reason = self._rule_refusal(combo)
        if reason is not None:
            self._note_refusal(combo, reason)
            self.on_combo_refused(combo, reason)
            return combo
        identified = replace(combo, id=self._combos.next_id())
        orders = [self._leg_order(leg, identified.id) for leg in identified.legs]
        self._combos.opening(identified, orders)
        self.submit_order_list(orders)
        return identified

    def _note_refusal(self, combo: Combo, reason: str) -> None:
        legs = tuple(str(leg.contract.id) for leg in combo.legs)
        logger.warning("combo refused: %s: %s", ", ".join(legs), reason)
        self.refusals.append(Refusal(self.clock.timestamp_ns(), legs, reason))

    def close_combo(self, combo: Combo) -> None:
        """Close the legs of an open ``combo`` still held with market orders,
        together; a combo already closing is left alone."""
        if combo.id not in {each.id for each in self.combos}:
            return
        if self._combos.is_closing(combo.id):
            return
        held = self._combos.remaining(combo.id)
        orders = [
            self._closing_order(leg, held[leg.contract.id], combo.id)
            for leg in combo.legs
            if leg.contract.id in held
        ]
        self._combos.closing(combo.id, orders)
        self.submit_order_list(orders)

    def margin_of_combo(self, combo: Combo) -> Decimal:
        """The initial margin of the legs of ``combo``, each as a position of its
        own, in the settlement currency, as of now; zero without a margin model."""
        if self._margin is None:
            return Decimal(0)
        return self._margin.of_quantities(
            {leg.contract.id: _signed_leg(leg) for leg in combo.legs}
        )

    def use_margin(self, model: MarginModel) -> None:
        """Margin the strategy's orders and positions with ``model``."""
        self._margin = MarginDesk(model, weakref.proxy(self))

    def use_history(self, histories: Mapping[str, ChainHistory]) -> None:
        """Tell a chain strategy what the run knew of each chain, by underlying,
        before its start: the data before the start of a run is not streamed."""
        self._markets.preload(histories)

    def margin_of_order(self, order: Any) -> Decimal:
        """The initial margin ``order`` adds to its position, in the settlement
        currency, as of now; zero when it only reduces the position or the run
        has no margin model."""
        return Decimal(0) if self._margin is None else self._margin.of_order(order)

    def margin_of_positions(self) -> dict[InstrumentId, Decimal]:
        """The initial margin of each open position, in the settlement currency,
        as of now; none without a margin model."""
        return {} if self._margin is None else self._margin.of_positions()

    def on_margin_refused(self, order: Any, reason: str) -> None:
        """``order`` was not sent: its initial margin is more than the free
        equity, ``reason`` says by how much."""

    def on_combo_refused(self, combo: Combo, reason: str) -> None:
        """``combo`` was not sent: it breaks a short premium rule, ``reason`` names
        the rule and the numbers."""

    def on_settlement(self, fill: OrderFilled) -> None:
        """A position settled at its contract's expiry; ``fill`` closed it."""

    def on_combo_opened(self, combo: Combo) -> None:
        """Every leg of ``combo`` is filled; its legs hold their entry prices."""

    def on_combo_closed(self, combo: Combo) -> None:
        """The last leg of ``combo`` was closed."""

    def on_combo_settled(self, combo: Combo) -> None:
        """``combo`` was closed at expiry, at least in part by settlement."""

    def on_combo_failed(self, combo: Combo, reason: str) -> None:
        """A leg of ``combo`` was refused while it opened; the legs that filled are
        closed and the combo is never open."""

    def on_order_denied(self, event: OrderDenied) -> None:
        self._hear_failure(event)

    def on_order_rejected(self, event: OrderRejected) -> None:
        self._hear_failure(event)

    def on_order_filled(self, event: OrderFilled) -> None:
        self._hear_fill(event)

    def on_bar(self, bar: Bar) -> None:
        self._watch_drawdown(bar)

    def on_option_greeks(self, greeks: OptionGreeks) -> None:
        self._hear_market(greeks)

    def on_index_price(self, index_price: IndexPriceUpdate) -> None:
        self._hear_market(index_price)

    def on_schedule(self, now: datetime) -> None:
        """The strategy's ``schedule`` interval passed; ``now`` is the time of the
        tick. Like the bars, it ticks during warm-up too."""

    def _listen_to_market(self) -> None:
        """A chain run hears the IV of its contracts, the index and the DVOL."""
        for feed in self._markets.series():
            self.subscribe_index_prices(feed)
        if self._markets.feeds:
            for contract_id in self.instrument_ids:
                self.subscribe_option_greeks(contract_id)

    def _hear_market(self, event: OptionGreeks | IndexPriceUpdate) -> None:
        if isinstance(event, OptionGreeks):
            self._markets.hear_greeks(event)
        else:
            self._markets.hear_index_price(event)

    def _arm_schedule(self) -> None:
        interval = self.schedule(self.params)
        if interval is not None:
            self.clock.set_timer("schedule", interval, callback=self._tick)

    def _arm_greeks(self) -> None:
        if self._greeks is not None:
            self.clock.set_timer(
                "portfolio-greeks", _GREEKS_INTERVAL, callback=self._sample_greeks
            )

    @_recording_failure
    def _sample_greeks(self, event: TimeEvent) -> None:
        if self._greeks is None or self.warming_up:
            return
        try:
            self.portfolio_greeks.append(self._greeks.sample(event.ts_event))
        except NoMarketError:
            return

    def _tick(self, event: TimeEvent) -> None:
        now = unix_nanos_to_dt(event.ts_event)
        self._close_combos(now)
        self.on_schedule(now)

    def _arm_settlement(self) -> None:
        for instrument_id in self.instrument_ids:
            time = settlement_time(self.cache.instrument(instrument_id))
            if time is not None and time > self.clock.timestamp_ns():
                self.clock.set_time_alert_ns(
                    f"settle-{instrument_id}",
                    time,
                    functools.partial(self._settle, instrument_id),
                )

    @_recording_failure
    def _settle(self, instrument_id: InstrumentId, event: TimeEvent) -> None:
        del event
        self.cancel_all_orders(instrument_id)
        positions = self.cache.positions_open(
            instrument_id=instrument_id, strategy_id=self.strategy_id
        )
        for position in positions:
            order = self.order_factory.market(
                instrument_id,
                closing_side(position),
                position.quantity,
                tags=[
                    SETTLEMENT_TAG,
                    *map(combo_tag, self._combos.holding(instrument_id)),
                ],
            )
            self._settling.add(order.client_order_id)
            self._combos.settling(instrument_id, order)
            super().submit_order(order, position_id=position.id)

    def _hear_fill(self, event: OrderFilled) -> None:
        if event.client_order_id in self._settling:
            self._settling.discard(event.client_order_id)
            self.on_settlement(event)
        for change, combo in self._combos.hear(event):
            if change == Change.LATE_FILL:
                self._unwind(combo)
            else:
                self._hook(change)(combo)

    def _hear_failure(self, event: OrderDenied | OrderRejected) -> None:
        combo = self._combos.fail(event.client_order_id)
        if combo is not None:
            self._unwind(combo)
            self.on_combo_failed(combo, str(event.reason))

    def _unwind(self, combo: Combo) -> None:
        owed = self._combos.unwind(combo.id)
        orders = [
            self._closing_order(leg, owed[leg.contract.id], combo.id)
            for leg in combo.legs
            if leg.contract.id in owed
        ]
        if orders:
            self.submit_order_list(orders)

    def _hook(self, change: Change) -> Callable[[Combo], None]:
        return {
            Change.OPENED: self.on_combo_opened,
            Change.CLOSED: self.on_combo_closed,
            Change.SETTLED: self.on_combo_settled,
        }[change]

    def _leg_order(self, leg: Leg, combo_id: str) -> Any:
        return self.order_factory.market(
            leg.contract.id,
            leg.side,
            Quantity.from_str(str(leg.quantity)),
            tags=[combo_tag(combo_id)],
        )

    def _closing_order(self, leg: Leg, held: Decimal, combo_id: str) -> Any:
        return self._leg_order(
            replace(leg, side=_opposite(leg.side), quantity=held), combo_id
        )

    def _close_combos(self, now: datetime) -> None:
        rule = self.combo_exit(self.params)
        if rule is None:
            return
        chains = self.chains
        for combo in self.combos:
            chain = chains[combo.legs[0].contract.underlying.code]
            if rule.reached(combo, now, chain.quote):
                self.close_combo(combo)

    def _subscribed(self, bar_type: BarType) -> BarType:
        """Nautilus delivers a composite bar type's bars under its standard type."""
        if self._aggregated_from is None:
            return bar_type
        return BarType.from_str(f"{bar_type}@{self._aggregated_from}")

    def submit_order(self, order: Any, *args: Any, **kwargs: Any) -> None:
        if self._takes_orders and self._covered([order]):
            super().submit_order(order, *args, **kwargs)

    def submit_order_list(self, order_list: Any, *args: Any, **kwargs: Any) -> None:
        if self._takes_orders and self._covered(order_list):
            super().submit_order_list(order_list, *args, **kwargs)
        else:
            self._combos.forget(order_list)

    def _rule_refusal(self, combo: Combo) -> str | None:
        if self._rules is None or not self._takes_orders:
            return None
        return self._rules.refusal(combo)

    def _covered(self, orders: Sequence[Any]) -> bool:
        """Whether the free equity covers the orders; if not, the strategy hears
        why."""
        reason = None if self._margin is None else self._margin.refusal(orders)
        if reason is not None:
            self.on_margin_refused(orders[0], reason)
        return reason is None

    @property
    def _takes_orders(self) -> bool:
        return not self.warming_up and self.drawdown_tripped_at is None

    def _watch_drawdown(self, bar: Bar) -> None:
        if self._drawdown is None or not self._takes_orders:
            return
        if self._drawdown.breached(self._total_equity(bar.bar_type.instrument_id)):
            self.market_exit()
            self.drawdown_tripped_at = unix_nanos_to_dt(bar.ts_event)

    def _total_equity(self, instrument_id: InstrumentId) -> Decimal:
        """Balance plus unrealized PnL, in the instrument's settlement currency."""
        instrument = self.cache.instrument(instrument_id)
        account = self.portfolio.account(instrument_id.venue)
        if instrument is None or account is None:
            raise RuntimeError(f"no instrument or account to value {instrument_id}")
        currency = instrument.settlement_currency
        amounts = (
            account.balance_total(currency),
            self.portfolio.unrealized_pnls(instrument_id.venue).get(currency),
        )
        return sum(
            (money.as_decimal() for money in amounts if money is not None), Decimal(0)
        )


def _watching_drawdown(handler: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(handler)
    def watched(self: Strategy[Any], bar: Bar) -> Any:
        self._watch_drawdown(bar)
        return handler(self, bar)

    return watched


def _hearing_market(handler: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(handler)
    def heard(self: Strategy[Any], event: OptionGreeks | IndexPriceUpdate) -> Any:
        self._hear_market(event)
        return handler(self, event)

    return heard


def _signed_leg(leg: Leg) -> Decimal:
    return -leg.quantity if leg.is_short else leg.quantity


def _opposite(side: OrderSide) -> OrderSide:
    return OrderSide.BUY if side == OrderSide.SELL else OrderSide.SELL


def _hearing_failure(handler: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(handler)
    def heard(self: Strategy[Any], event: OrderDenied | OrderRejected) -> Any:
        self._hear_failure(event)
        return handler(self, event)

    return heard


def _hearing_settlement(handler: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(handler)
    def heard(self: Strategy[Any], event: OrderFilled) -> Any:
        self._hear_fill(event)
        return handler(self, event)

    return heard


_HEARING: dict[str, Callable[[Callable[..., Any]], Callable[..., Any]]] = {
    "on_bar": _watching_drawdown,
    "on_order_filled": _hearing_settlement,
    "on_order_denied": _hearing_failure,
    "on_order_rejected": _hearing_failure,
    "on_option_greeks": _hearing_market,
    "on_index_price": _hearing_market,
}


class UnknownParameterError(ValueError):
    pass


class InvalidParameterError(ValueError):
    pass


_LOAD_LOCK = threading.Lock()


def import_strategy(path: str, source: Path | None = None) -> type[Strategy[Any]]:
    """Import a strategy class from ``"package.module:Class"``.

    With ``source``, the module is the file ``source``, loaded under a name of
    its own that its content fixes, without touching ``sys.path``: modules of
    one name and different sources each keep their own classes.
    """
    module_name, _, class_name = path.partition(":")
    if source is None:
        module = importlib.import_module(module_name)
    else:
        module = _module_from(module_name, source)
    strategy = getattr(module, class_name)
    if not (isinstance(strategy, type) and issubclass(strategy, Strategy)):
        raise TypeError(f"{path} is not an sbt2 Strategy subclass")
    return strategy


def strategy_source(path: str) -> str:
    """The source of the module that defines the strategy at ``path``."""
    strategy = import_strategy(path)
    file = inspect.getsourcefile(strategy)
    if file is None:
        raise TypeError(f"{path} has no source file to keep")
    return Path(file).read_text()


def _module_from(name: str, source: Path) -> ModuleType:
    code = source.read_bytes()
    private = (
        f"_sbt2_stored_{hashlib.sha256(code).hexdigest()[:16]}_{name.replace('.', '_')}"
    )
    with _LOAD_LOCK:
        if private not in sys.modules:
            _load(private, source)
        return sys.modules[private]


def _load(name: str, source: Path) -> None:
    spec = importlib.util.spec_from_file_location(name, source)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load a module from {source}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        del sys.modules[name]
        raise


def resolve_params(strategy: type[Strategy[Any]], values: Mapping[str, Any]) -> Any:
    """Build ``strategy.Params`` from plain values, filling in the defaults.

    Values arrive as TOML or JSON primitives, so a decimal may come as a string
    or a number and a float as an integer.
    """
    _reject_unknown(strategy, values)
    kinds = get_type_hints(strategy.Params)
    return strategy.Params(
        **{name: _typed(name, value, kinds[name]) for name, value in values.items()}
    )


def _reject_unknown(strategy: type[Strategy[Any]], values: Mapping[str, Any]) -> None:
    valid = {field.name for field in fields(strategy.Params)}
    unknown = sorted(set(values) - valid)
    if unknown:
        raise UnknownParameterError(
            f"unknown parameters {', '.join(unknown)} for {strategy.__name__}; "
            f"valid: {', '.join(sorted(valid)) or 'none'}"
        )


def _typed(name: str, value: Any, kind: Any) -> Any:
    if get_origin(kind) is Literal:
        return _chosen(name, value, get_args(kind))
    if is_str_tuple(kind):
        return _names(name, value)
    if not isinstance(kind, type):
        return value
    if isinstance(value, kind) and not (isinstance(value, bool) and kind is not bool):
        return value
    if kind is Decimal and isinstance(value, str | int | float):
        return _decimal(name, value)
    if kind is float and type(value) is int:
        return float(value)
    raise InvalidParameterError(
        f"parameter {name} must be {kind.__name__}, got {value!r}"
    )


def _names(name: str, value: Any) -> tuple[str, ...]:
    if isinstance(value, tuple | list) and all(isinstance(each, str) for each in value):
        return tuple(value)
    raise InvalidParameterError(
        f"parameter {name} must be a list of str, got {value!r}"
    )


def _decimal(name: str, value: str | float) -> Decimal:
    try:
        return Decimal(str(value))
    except ArithmeticError:
        raise InvalidParameterError(
            f"parameter {name} must be a decimal, got {value!r}"
        ) from None


def _chosen(name: str, value: Any, choices: tuple[Any, ...]) -> Any:
    typed = _typed(name, value, type(choices[0]))
    if typed not in choices:
        listed = ", ".join(repr(each) for each in choices)
        raise InvalidParameterError(
            f"parameter {name} must be one of {listed}, got {value!r}"
        )
    return typed
