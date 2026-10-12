import inspect
import types
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any

from nautilus_trader.execution import (
    CappedOptionFeeModel,
    DefaultFillModel,
    FixedFeeModel,
    MakerTakerFeeModel,
)
from nautilus_trader.model import Money

from sbt2.core.spec.errors import SpecError


class FeeModelKind(StrEnum):
    MAKER_TAKER = "maker_taker"
    FIXED = "fixed"
    CAPPED_OPTION = "capped_option"


class FillModelKind(StrEnum):
    DEFAULT = "default"


class UnknownModelKindError(SpecError, LookupError):
    pass


class InvalidModelConfigError(SpecError):
    pass


@dataclass(frozen=True)
class ModelParameter:
    """A parameter of a model kind's config. ``type`` is ``str``, ``int``,
    ``float`` or ``bool``; ``str`` also stands for a parameter whose type cannot
    be told. ``default`` is ``None`` when there is none."""

    name: str
    type: type
    required: bool
    default: Any = None


_DESCRIBED = (bool, int, float, str)


def _fixed_fee(
    commission: str, *, charge_commission_once: bool | None = None
) -> FixedFeeModel:
    """A TOML table holds no ``Money``, so the commission comes as its string."""
    return FixedFeeModel(Money.from_str(commission), charge_commission_once)


def _capped_option_fee(
    maker_rate: str, taker_rate: str, cap_rate: str
) -> CappedOptionFeeModel:
    """The nautilus model takes ``Decimal`` rates and has no named parameters."""
    return CappedOptionFeeModel(
        Decimal(maker_rate), Decimal(taker_rate), Decimal(cap_rate)
    )


_MODELS: Mapping[str, Mapping[str, Callable[..., Any]]] = {
    "fee_model": {
        FeeModelKind.MAKER_TAKER: MakerTakerFeeModel,
        FeeModelKind.FIXED: _fixed_fee,
        FeeModelKind.CAPPED_OPTION: _capped_option_fee,
    },
    "fill_model": {FillModelKind.DEFAULT: DefaultFillModel},
    "latency_model": {},
    "margin_model": {},
    "modules": {},
}


def model_kinds() -> dict[str, dict[str, tuple[ModelParameter, ...]]]:
    """Each model argument's kinds, and the config parameters of each kind."""
    return {
        argument: {kind: _parameters(builder) for kind, builder in builders.items()}
        for argument, builders in _MODELS.items()
    }


def _parameters(builder: Callable[..., Any]) -> tuple[ModelParameter, ...]:
    return tuple(
        _parameter(each)
        for each in inspect.signature(builder).parameters.values()
        if each.kind not in {each.VAR_POSITIONAL, each.VAR_KEYWORD}
    )


def _parameter(parameter: inspect.Parameter) -> ModelParameter:
    required = parameter.default is parameter.empty
    default = None if required else parameter.default
    return ModelParameter(
        parameter.name, _type(parameter.annotation, default), required, default
    )


def _type(annotation: Any, default: Any) -> type:
    if isinstance(annotation, types.UnionType):
        described = [each for each in annotation.__args__ if each is not type(None)]
        annotation = described[0] if len(described) == 1 else None
    for each in _DESCRIBED:
        if annotation is each or (
            annotation is inspect.Parameter.empty and isinstance(default, each)
        ):
            return each
    return str


_RUN_SETTINGS = frozenset({"quotes", "delivery_fee", "margin"})


def venue_objects(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """The ``BacktestVenueConfig`` arguments of the venue arguments: each
    ``{kind, config}`` model table built, the run's own settings left out."""
    built = {
        argument: _built(argument, value)
        for argument, value in arguments.items()
        if argument in _MODELS
    }
    own = {k: v for k, v in arguments.items() if k not in _RUN_SETTINGS}
    return {**own, **built}


def model_tables(
    arguments: Mapping[str, Any],
) -> Iterator[tuple[str, Mapping[str, Any]]]:
    """Each model table of the venue ``arguments``, with the argument that holds
    it; ``modules`` holds a list of them."""
    for argument, value in arguments.items():
        if argument == "modules":
            yield from ((argument, each) for each in value)
        elif argument in _MODELS:
            yield argument, value


def built_model(argument: str, table: Mapping[str, Any]) -> Any:
    """The nautilus model the ``{kind, config}`` ``table`` of ``argument`` names."""
    kind = table["kind"]
    builder = _builder(argument, kind)
    try:
        return builder(**table.get("config", {}))
    except (TypeError, ValueError) as error:
        raise InvalidModelConfigError(
            f"{argument} {kind} cannot be built from its config: {error}"
        ) from error


def _builder(argument: str, kind: str) -> Callable[..., Any]:
    builders = _MODELS[argument]
    if kind not in builders:
        known = ", ".join(sorted(builders)) or "none"
        raise UnknownModelKindError(f"no {argument} kind {kind}; known: {known}")
    return builders[kind]


def _built(argument: str, value: Any) -> Any:
    if argument == "modules":
        return [built_model(argument, each) for each in value]
    return built_model(argument, value)
