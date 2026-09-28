import importlib
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar, get_type_hints

from nautilus_trader.core import dt_to_unix_nanos
from nautilus_trader.model import (
    AggregationSource,
    BarSpecification,
    BarType,
    InstrumentId,
)
from nautilus_trader.trading import ImportableStrategyConfig
from nautilus_trader.trading import Strategy as NautilusStrategy


@dataclass(frozen=True)
class NoParams:
    pass


@dataclass(frozen=True)
class StrategyRun:
    """What to run: a strategy import path, its instruments and parameters.

    ``trade_start`` is the segment start; before it the strategy only warms up.
    """

    strategy: str
    instruments: Sequence[InstrumentId]
    params: Mapping[str, Any]
    trade_start: datetime


@dataclass(frozen=True)
class RunConfig:
    """``StrategyRun`` as the JSON primitives nautilus passes to the strategy."""

    instruments: list[str]
    params: dict[str, Any]
    trade_start: str


def importable_config(run: StrategyRun) -> ImportableStrategyConfig:
    config = RunConfig(
        [str(each) for each in run.instruments],
        dict(run.params),
        run.trade_start.isoformat(),
    )
    return ImportableStrategyConfig(
        run.strategy, f"{__name__}:RunConfig", asdict(config)
    )


class Strategy[P](NautilusStrategy, ABC):
    """A nautilus strategy that sbt2 can describe without running it.

    ``Params`` is a dataclass: its fields are the parameter schema and defaults.
    ``inputs`` declares the bars the strategy needs; they are aggregated at run
    time from trades and subscribed on start, so a subclass that
    overrides ``on_start`` calls ``super().on_start()``. Orders submitted while
    ``warming_up`` are dropped.
    """

    Params: ClassVar[type[Any]] = NoParams

    def __init__(self, config: RunConfig) -> None:
        super().__init__(config)
        self.params: P = resolve_params(type(self), config.params)
        self.instrument_ids = [
            InstrumentId.from_str(each) for each in config.instruments
        ]
        self._trade_start_ns = dt_to_unix_nanos(config.trade_start)

    @classmethod
    def warmup(cls, params: P) -> timedelta:
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
            self.subscribe_bars(bar_type)

    def submit_order(self, order: Any, *args: Any, **kwargs: Any) -> None:
        if not self.warming_up:
            super().submit_order(order, *args, **kwargs)

    def submit_order_list(self, order_list: Any, *args: Any, **kwargs: Any) -> None:
        if not self.warming_up:
            super().submit_order_list(order_list, *args, **kwargs)


class UnknownParameterError(ValueError):
    pass


class InvalidParameterError(ValueError):
    pass


def import_strategy(path: str) -> type[Strategy[Any]]:
    """Import a strategy class from ``"package.module:Class"``."""
    module_name, _, class_name = path.partition(":")
    strategy = getattr(importlib.import_module(module_name), class_name)
    if not (isinstance(strategy, type) and issubclass(strategy, Strategy)):
        raise TypeError(f"{path} is not an sbt2 Strategy subclass")
    return strategy


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
