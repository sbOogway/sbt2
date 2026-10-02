from collections.abc import Callable, Iterator, Mapping
from enum import StrEnum
from typing import Any

from nautilus_trader.execution import (
    DefaultFillModel,
    FixedFeeModel,
    MakerTakerFeeModel,
)
from nautilus_trader.model import Money

from sbt2.core.spec.errors import SpecError


class FeeModelKind(StrEnum):
    MAKER_TAKER = "maker_taker"
    FIXED = "fixed"


class FillModelKind(StrEnum):
    DEFAULT = "default"


class UnknownModelKindError(SpecError, LookupError):
    pass


def _fixed_fee(commission: str, **rest: Any) -> FixedFeeModel:
    """A TOML table holds no ``Money``, so the commission comes as its string."""
    return FixedFeeModel(Money.from_str(commission), **rest)


_MODELS: Mapping[str, Mapping[str, Callable[..., Any]]] = {
    "fee_model": {
        FeeModelKind.MAKER_TAKER: MakerTakerFeeModel,
        FeeModelKind.FIXED: _fixed_fee,
    },
    "fill_model": {FillModelKind.DEFAULT: DefaultFillModel},
    "latency_model": {},
    "margin_model": {},
    "modules": {},
}


def venue_objects(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Venue arguments with each ``{kind, config}`` model table built."""
    built = {
        argument: _built(argument, value)
        for argument, value in arguments.items()
        if argument in _MODELS
    }
    return {**arguments, **built}


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


def model_builder(argument: str, kind: str) -> Callable[..., Any]:
    builders = _MODELS[argument]
    if kind not in builders:
        known = ", ".join(sorted(builders)) or "none"
        raise UnknownModelKindError(f"no {argument} kind {kind}; known: {known}")
    return builders[kind]


def _built(argument: str, value: Any) -> Any:
    if argument == "modules":
        return [_model(argument, each) for each in value]
    return _model(argument, value)


def _model(argument: str, table: Mapping[str, Any]) -> Any:
    return model_builder(argument, table["kind"])(**table.get("config", {}))
