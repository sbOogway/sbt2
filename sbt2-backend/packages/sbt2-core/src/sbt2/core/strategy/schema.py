from dataclasses import MISSING, dataclass, fields
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, get_args, get_origin, get_type_hints

if TYPE_CHECKING:
    from sbt2.core.strategy.base import Strategy

_KINDS: tuple[type, ...] = (int, float, Decimal, str, bool)


@dataclass(frozen=True)
class ParamSpec:
    """One field of a strategy's ``Params``: what a form needs to ask for it.

    ``default`` is ``None`` for a required field. ``choices`` is empty unless
    the field is a ``Literal``; then ``kind`` is the type of its members.
    """

    name: str
    kind: type
    required: bool
    default: Any = None
    choices: tuple[Any, ...] = ()


class UnsupportedParameterTypeError(TypeError):
    pass


def params_schema(strategy: type[Strategy[Any]]) -> tuple[ParamSpec, ...]:
    """The fields of ``strategy.Params``, in order.

    Raises ``UnsupportedParameterTypeError`` for a field that is not an int,
    float, Decimal, str, bool or a ``Literal`` of members of one of them.
    """
    hints = get_type_hints(strategy.Params)
    return tuple(
        _spec(field.name, hints[field.name], field.default)
        for field in fields(strategy.Params)
    )


def _spec(name: str, hint: Any, default: Any) -> ParamSpec:
    kind, choices = _kind_and_choices(name, hint)
    required = default is MISSING
    return ParamSpec(name, kind, required, None if required else default, choices)


def _kind_and_choices(name: str, hint: Any) -> tuple[type, tuple[Any, ...]]:
    if get_origin(hint) is Literal:
        choices = get_args(hint)
        kinds = {type(each) for each in choices}
        if len(kinds) == 1 and kinds <= set(_KINDS):
            return kinds.pop(), choices
    elif hint in _KINDS:
        return hint, ()
    raise UnsupportedParameterTypeError(
        f"parameter {name} has the unsupported type {_describe(hint)}"
    )


def _describe(hint: Any) -> str:
    if get_origin(hint) is Literal:
        return f"Literal[{', '.join(repr(each) for each in get_args(hint))}]"
    if isinstance(hint, type) and not get_args(hint):
        return hint.__name__
    return str(hint).replace("typing.", "")
