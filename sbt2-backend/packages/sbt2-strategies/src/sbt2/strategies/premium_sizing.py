from collections.abc import Sequence
from decimal import Decimal


def kelly_fraction(risk_free: float, dte: float, pop: float) -> float:
    """Equation 8.1 of the book: the share of the capital to risk on a trade
    of ``dte`` days with a probability of profit ``pop``."""
    return risk_free * dte / 365 * pop / (1 - pop)


def shared_fractions(
    fractions: Sequence[float],
    correlation: Sequence[Sequence[float]],
    threshold: float,
) -> list[float]:
    """``fractions`` of the underlyings, where those linked by a correlation of
    ``threshold`` or more, directly or through others, share the larger one."""
    group = list(range(len(fractions)))
    for first, row in enumerate(correlation):
        for second, each in enumerate(row):
            if each >= threshold:
                _join(group, first, second)
    largest: dict[int, float] = {}
    for index, fraction in enumerate(fractions):
        root = _root(group, index)
        largest[root] = max(largest.get(root, fraction), fraction)
    return [largest[_root(group, index)] for index in range(len(fractions))]


def proportions(fractions: Sequence[float]) -> list[float]:
    """``fractions`` scaled to sum to one."""
    total = sum(fractions)
    return [each / total for each in fractions]


def contract_quantity(target: Decimal, one_contract: Decimal, step: Decimal) -> Decimal:
    """How many contracts, a multiple of ``step``, have a margin of at most
    ``target`` when one has ``one_contract``; zero when not even one step fits."""
    steps = int(target / one_contract / step)
    return step * steps


def _root(group: list[int], index: int) -> int:
    while group[index] != index:
        index = group[index]
    return index


def _join(group: list[int], first: int, second: int) -> None:
    group[_root(group, second)] = _root(group, first)
