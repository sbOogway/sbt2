import importlib
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar, get_type_hints

from nautilus_trader.model import Bar, BarType, InstrumentId, Money


@dataclass(frozen=True)
class Bars:
    """Time bars aggregated at run time from trades, e.g. ``Bars("1-MINUTE-LAST")``."""

    spec: str

    def bar_type(self, instrument_id: InstrumentId) -> BarType:
        return BarType.from_str(f"{instrument_id}-{self.spec}-INTERNAL")


type Input = Bars


@dataclass(frozen=True)
class State:
    time: datetime
    bars: Mapping[BarType, Bar]
    positions: Mapping[InstrumentId, Decimal]
    equity: Money


@dataclass(frozen=True)
class TargetPosition:
    """The signed net position wanted on an instrument, reached with market orders."""

    instrument_id: InstrumentId
    quantity: Decimal


type Intent = TargetPosition


@dataclass(frozen=True)
class Fill:
    instrument_id: InstrumentId
    quantity: Decimal
    price: Decimal
    time: datetime


@dataclass(frozen=True)
class NoParams:
    pass


class Strategy[P](ABC):
    """A plain-Python strategy: it reads state and returns intents, never orders.

    ``Params`` is a dataclass: its fields are the parameter schema and defaults.
    """

    Params: ClassVar[type[Any]] = NoParams

    def __init__(self, params: P) -> None:
        self.params = params

    @classmethod
    def warmup(cls, params: P) -> timedelta:
        return timedelta(0)

    @classmethod
    @abstractmethod
    def inputs(cls, params: P) -> Sequence[Input]: ...

    @abstractmethod
    def decide(self, state: State) -> Sequence[Intent]: ...

    def on_fill(self, fill: Fill) -> None:
        return None


class UnknownParameterError(ValueError):
    pass


class InvalidParameterError(ValueError):
    pass


def import_strategy(path: str) -> type[Strategy[Any]]:
    """Import a strategy class from ``"package.module:Class"``."""
    module_name, _, class_name = path.partition(":")
    strategy = getattr(importlib.import_module(module_name), class_name)
    if not (isinstance(strategy, type) and issubclass(strategy, Strategy)):
        raise TypeError(f"{path} is not a Strategy subclass")
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
