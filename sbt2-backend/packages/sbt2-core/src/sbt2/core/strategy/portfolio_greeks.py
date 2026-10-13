from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from nautilus_trader.model import CryptoOption, InstrumentId, PositionSide

from sbt2.core.market import underlying_index
from sbt2.core.strategy.book_rules import account_equity
from sbt2.core.strategy.chain import NoMarketError

BETA = 1.0


@dataclass(frozen=True)
class Holding:
    """An open position: ``quantity`` is signed; ``delta`` and ``theta`` are the
    contract's own, per contract, ``theta`` in USD per day."""

    contract: CryptoOption
    quantity: Decimal
    delta: float
    theta: float = 0.0


@dataclass(frozen=True)
class GreeksSample:
    """The portfolio greeks at ``ts_event`` (ns): ``theta`` per day in the
    settlement currency, ``theta_ratio`` as its share of equity, and the delta
    in BTC weighted by beta."""

    ts_event: int
    theta: float
    theta_ratio: float
    beta_weighted_delta: float


def beta_weighted_delta(
    holdings: Sequence[Holding], indexes: Mapping[InstrumentId, float]
) -> float:
    """The delta of ``holdings`` in BTC: each position's delta times its
    underlying index over the BTC index and its beta, which is 1 for every
    underlying. ``KeyError`` when a position needs an index price missing from
    ``indexes``."""
    return sum((_weighted(each, indexes) for each in holdings), 0.0)


def portfolio_theta(
    holdings: Sequence[Holding], indexes: Mapping[InstrumentId, float]
) -> float:
    """The theta per day of ``holdings`` in the coin of each underlying, which
    its index price converts from USD. ``KeyError`` as ``beta_weighted_delta``."""
    return sum(
        (
            float(each.quantity) * each.theta / indexes[_index_of(each.contract)]
            for each in holdings
        ),
        0.0,
    )


class GreeksDesk:
    """Samples the greeks of the positions a strategy holds, priced by its chain
    and the latest price of its ``index``."""

    def __init__(
        self, strategy: Any, index: InstrumentId, latest: Callable[[], float | None]
    ) -> None:
        self._strategy = strategy
        self._index = index
        self._latest = latest

    def sample(self, ts_event: int) -> GreeksSample:
        """The greeks now; all zero when the book is flat. ``NoMarketError`` when
        a position cannot be priced yet."""
        holdings = self._holdings()
        if not holdings:
            return GreeksSample(ts_event, 0.0, 0.0, 0.0)
        indexes = self._indexes()
        try:
            theta = portfolio_theta(holdings, indexes)
            delta = beta_weighted_delta(holdings, indexes)
        except KeyError as error:
            raise NoMarketError(f"no index price for {error}") from error
        equity = float(account_equity(self._strategy, holdings[0].contract))
        return GreeksSample(ts_event, theta, theta / equity if equity else 0.0, delta)

    def _holdings(self) -> list[Holding]:
        cache = self._strategy.cache
        held: list[Holding] = []
        for position in cache.positions_open(strategy_id=self._strategy.strategy_id):
            contract = cache.instrument(position.instrument_id)
            if isinstance(contract, CryptoOption):
                greeks = self._strategy.chain.greeks(contract)
                held.append(
                    Holding(contract, _signed(position), greeks.delta, greeks.theta)
                )
        return held

    def _indexes(self) -> dict[InstrumentId, float]:
        price = self._latest()
        if price is None:
            raise NoMarketError("the chain has heard no index price yet")
        return {self._index: price}


def _signed(position: Any) -> Decimal:
    quantity = Decimal(str(position.quantity))
    return quantity if position.side == PositionSide.LONG else -quantity


def _index_of(contract: CryptoOption, code: str | None = None) -> InstrumentId:
    """The index of the underlying ``code`` (the contract's own by default) on the
    contract's venue."""
    return underlying_index(code or contract.underlying.code, contract.id.venue.value)


def _weighted(holding: Holding, indexes: Mapping[InstrumentId, float]) -> float:
    own = _index_of(holding.contract)
    base = _index_of(holding.contract, "BTC")
    ratio = 1.0 if own == base else indexes[own] / indexes[base]
    return float(holding.quantity) * holding.delta * ratio * BETA
