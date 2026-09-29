from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sbt2.spec.errors import SpecError

_DRAWDOWN_LIMIT = "drawdown_limit"
_ENGINE_KEYS = frozenset(
    {"max_notional_per_order", "max_order_submit_rate", "max_order_modify_rate"}
)


class UnknownRiskKeyError(SpecError):
    pass


class DrawdownLimitError(SpecError):
    pass


@dataclass(frozen=True)
class RiskLimits:
    """A spec's risk table, split by who enforces it.

    ``engine`` holds nautilus's ``RiskEngineConfig`` arguments;
    ``drawdown_limit`` is the fraction of peak equity the strategy base lets
    the run lose.
    """

    engine: Mapping[str, Any]
    drawdown_limit: Decimal | None


def risk_limits(table: Mapping[str, Any]) -> RiskLimits:
    _reject_unknown(table)
    engine = {key: value for key, value in table.items() if key in _ENGINE_KEYS}
    limit = table.get(_DRAWDOWN_LIMIT)
    return RiskLimits(engine, None if limit is None else _drawdown_limit(limit))


def _reject_unknown(table: Mapping[str, Any]) -> None:
    valid = _ENGINE_KEYS | {_DRAWDOWN_LIMIT}
    unknown = sorted(set(table) - valid)
    if unknown:
        raise UnknownRiskKeyError(
            f"unknown keys {', '.join(unknown)} in the risk table; "
            f"valid: {', '.join(sorted(valid))}"
        )


def _drawdown_limit(value: Any) -> Decimal:
    try:
        limit = Decimal(str(value))
        if 0 < limit < 1:
            return limit
    except InvalidOperation:
        pass
    raise DrawdownLimitError(
        f"drawdown limit {value!r} is not a fraction between 0 and 1"
    )
