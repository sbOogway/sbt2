from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sbt2.core.spec.errors import SpecError
from sbt2.core.strategy import ShortPremiumRules

_DRAWDOWN_LIMIT = "drawdown_limit"
_SHORT_PREMIUM = "short_premium"
_ENDS = 2
_SHORT_PREMIUM_KEYS = frozenset(
    {"allocation", "undefined_cap", "defined_cap", "defined_share"}
)
_ENGINE_KEYS = frozenset(
    {"max_notional_per_order", "max_order_submit_rate", "max_order_modify_rate"}
)


class UnknownRiskKeyError(SpecError):
    pass


class DrawdownLimitError(SpecError):
    pass


class ShortPremiumRuleError(SpecError):
    pass


@dataclass(frozen=True)
class RiskLimits:
    """A spec's risk table, split by who enforces it.

    ``engine`` holds nautilus's ``RiskEngineConfig`` arguments;
    ``drawdown_limit`` is the fraction of peak equity the strategy base lets
    the run lose; ``short_premium`` holds the portfolio rules the strategy base
    applies to the combos it opens, none when the table is absent.
    """

    engine: Mapping[str, Any]
    drawdown_limit: Decimal | None
    short_premium: ShortPremiumRules | None = None


def risk_limits(table: Mapping[str, Any]) -> RiskLimits:
    _reject_unknown(table, _ENGINE_KEYS | {_DRAWDOWN_LIMIT, _SHORT_PREMIUM}, "risk")
    engine = {key: value for key, value in table.items() if key in _ENGINE_KEYS}
    limit = table.get(_DRAWDOWN_LIMIT)
    rules = table.get(_SHORT_PREMIUM)
    return RiskLimits(
        engine,
        None if limit is None else _drawdown_limit(limit),
        None if rules is None else _short_premium(rules),
    )


def _reject_unknown(table: Mapping[str, Any], valid: frozenset[str], name: str) -> None:
    unknown = sorted(set(table) - valid)
    if unknown:
        raise UnknownRiskKeyError(
            f"unknown keys {', '.join(unknown)} in the {name} table; "
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


def _short_premium(table: Mapping[str, Any]) -> ShortPremiumRules:
    _reject_unknown(table, _SHORT_PREMIUM_KEYS, _SHORT_PREMIUM)
    defaults = ShortPremiumRules()
    return ShortPremiumRules(
        _allocation(table.get("allocation", defaults.allocation)),
        _fraction("undefined_cap", table.get("undefined_cap", defaults.undefined_cap)),
        _fraction("defined_cap", table.get("defined_cap", defaults.defined_cap)),
        _fraction("defined_share", table.get("defined_share", defaults.defined_share)),
    )


def _allocation(value: Any) -> tuple[Decimal, Decimal]:
    if isinstance(value, list | tuple) and len(value) == _ENDS:
        low, high = (_fraction("allocation", each) for each in value)
        if low <= high:
            return low, high
    raise ShortPremiumRuleError(
        f"short_premium allocation {value!r} is not two fractions between 0 and 1, "
        "the low end first"
    )


def _fraction(key: str, value: Any) -> Decimal:
    try:
        fraction = Decimal(str(value))
        if 0 < fraction <= 1:
            return fraction
    except InvalidOperation:
        pass
    raise ShortPremiumRuleError(
        f"short_premium {key} {value!r} is not a fraction between 0 and 1"
    )
