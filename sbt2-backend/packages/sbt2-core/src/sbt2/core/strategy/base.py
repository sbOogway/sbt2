import functools
import hashlib
import importlib
import importlib.util
import inspect
import sys
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, fields
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

from nautilus_trader.core import dt_to_unix_nanos, unix_nanos_to_dt
from nautilus_trader.model import (
    AggregationSource,
    Bar,
    BarSpecification,
    BarType,
    InstrumentId,
)
from nautilus_trader.trading import ImportableStrategyConfig
from nautilus_trader.trading import Strategy as NautilusStrategy

from sbt2.core.strategy.drawdown import DrawdownGuard

if TYPE_CHECKING:
    from sbt2.core.results import Benchmark


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
    """

    strategy: str
    instruments: Sequence[InstrumentId]
    params: Mapping[str, Any]
    trade_start: datetime
    aggregated_from: str | None = None
    drawdown_limit: Decimal | None = None


@dataclass(frozen=True)
class RunConfig:
    """``StrategyRun`` as the JSON primitives nautilus passes to the strategy."""

    instruments: list[str]
    params: dict[str, Any]
    trade_start: str
    aggregated_from: str | None = None
    drawdown_limit: str | None = None


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
    )


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

    With a drawdown limit, each bar after warm-up first checks total equity
    against its peak; once it falls the limit or more below, the strategy
    exits the market, records the bar's time in ``drawdown_tripped_at`` and
    drops every order after.
    """

    Params: ClassVar[type[Any]] = NoParams
    benchmark: ClassVar[Benchmark | None] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "on_bar" in vars(cls):
            cls.on_bar = _watching_drawdown(vars(cls)["on_bar"])
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
        self._drawdown = (
            None
            if config.drawdown_limit is None
            else DrawdownGuard(Decimal(config.drawdown_limit))
        )

    @classmethod
    def warmup(cls, _params: P, /) -> timedelta:
        return timedelta(0)

    @classmethod
    @abstractmethod
    def inputs(cls, params: P) -> Sequence[BarSpecification]: ...

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

    def on_bar(self, bar: Bar) -> None:
        self._watch_drawdown(bar)

    def _subscribed(self, bar_type: BarType) -> BarType:
        """Nautilus delivers a composite bar type's bars under its standard type."""
        if self._aggregated_from is None:
            return bar_type
        return BarType.from_str(f"{bar_type}@{self._aggregated_from}")

    def submit_order(self, order: Any, *args: Any, **kwargs: Any) -> None:
        if self._takes_orders:
            super().submit_order(order, *args, **kwargs)

    def submit_order_list(self, order_list: Any, *args: Any, **kwargs: Any) -> None:
        if self._takes_orders:
            super().submit_order_list(order_list, *args, **kwargs)

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
