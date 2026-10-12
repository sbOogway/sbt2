from dataclasses import dataclass

from nautilus_trader.model import CryptoOption, OptionKind, black_scholes_greeks

_YEAR_NS = 365 * 86_400 * 10**9


@dataclass(frozen=True)
class Greeks:
    """The Black-Scholes greeks of a contract in USD, the quote currency: delta
    per 1 of the index, gamma per 1 of the index squared, vega per IV point and
    theta per day."""

    delta: float
    gamma: float
    vega: float
    theta: float


@dataclass(frozen=True)
class Market:
    """What prices a contract: the ``index`` price and the ``iv`` as a fraction."""

    index: float
    iv: float


def greeks_of(contract: CryptoOption, market: Market, now_ns: int) -> Greeks:
    """The greeks of ``contract`` at ``now_ns``, with no rates, no carry and
    365-day years; ``ValueError`` when it has expired."""
    if contract.expiration_ns <= now_ns:
        raise ValueError(f"{contract.id} has expired")
    years = (contract.expiration_ns - now_ns) / _YEAR_NS
    result = black_scholes_greeks(
        market.index,
        0.0,
        0.0,
        market.iv,
        contract.option_kind == OptionKind.CALL,
        float(contract.strike_price),
        years,
    )
    return Greeks(result.delta, result.gamma, result.vega, result.theta)
