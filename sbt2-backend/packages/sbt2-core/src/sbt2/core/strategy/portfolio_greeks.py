from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from nautilus_trader.model import CryptoOption, InstrumentId, PositionSide

from sbt2.core.market import underlying_index
from sbt2.core.strategy.beta import BASE
from sbt2.core.strategy.chain import NoMarketError
from sbt2.core.strategy.conversion import Conversion
from sbt2.core.strategy.markets import Markets


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
    reporting currency, ``theta_ratio`` as its share of equity, and the delta
    in BTC weighted by beta."""

    ts_event: int
    theta: float
    theta_ratio: float
    beta_weighted_delta: float


def beta_weighted_delta(
    holdings: Sequence[Holding],
    indexes: Mapping[InstrumentId, float],
    betas: Mapping[str, float] | None = None,
) -> float:
    """The delta of ``holdings`` in BTC: each position's delta times its
    underlying index over the BTC index and the beta of the underlying to BTC in
    ``betas``, 1 for an underlying it lacks. ``KeyError`` when a position needs an
    index price missing from ``indexes``."""
    return sum((_weighted(each, indexes, betas or {}) for each in holdings), 0.0)


def portfolio_theta(
    holdings: Sequence[Holding], indexes: Mapping[InstrumentId, float], reporting: str
) -> float:
    """The theta per day of ``holdings`` in the ``reporting`` currency, which its
    index price converts from USD. ``KeyError`` as ``beta_weighted_delta``."""
    return sum(
        (
            float(each.quantity)
            * each.theta
            / indexes[_index_of(each.contract, reporting)]
            for each in holdings
        ),
        0.0,
    )


class GreeksDesk:
    """Samples the greeks of the positions a strategy holds, priced by the chain
    of each underlying and the index prices and betas ``markets`` heard. They are
    in the ``reporting`` currency, the underlying of the first chain by
    default."""

    def __init__(
        self, strategy: Any, markets: Markets, reporting: str | None = None
    ) -> None:
        self._strategy = strategy
        self._markets = markets
        self._reporting = reporting or markets.feeds[0].underlying
        self._conversion = Conversion(markets.prices)

    def sample(self, ts_event: int) -> GreeksSample:
        """The greeks now; all zero when the book is flat. ``NoMarketError`` when
        a position cannot be priced yet."""
        holdings = self._holdings()
        if not holdings:
            return GreeksSample(ts_event, 0.0, 0.0, 0.0)
        indexes = self._markets.indexes()
        try:
            theta = portfolio_theta(holdings, indexes, self._reporting)
            delta = beta_weighted_delta(holdings, indexes, self._markets.betas())
        except KeyError as error:
            raise NoMarketError(f"no index price for {error}") from error
        equity = float(self._equity(holdings[0].contract))
        return GreeksSample(ts_event, theta, theta / equity if equity else 0.0, delta)

    def _equity(self, contract: CryptoOption) -> Decimal:
        """The balances of all coins, in the reporting currency."""
        account = self._strategy.portfolio.account(contract.id.venue)
        return self._conversion.balances(account, self._reporting)

    def _holdings(self) -> list[Holding]:
        cache = self._strategy.cache
        chains = self._strategy.chains
        held: list[Holding] = []
        for position in cache.positions_open(strategy_id=self._strategy.strategy_id):
            contract = cache.instrument(position.instrument_id)
            if isinstance(contract, CryptoOption):
                greeks = chains[contract.underlying.code].greeks(contract)
                held.append(
                    Holding(contract, _signed(position), greeks.delta, greeks.theta)
                )
        return held


def _signed(position: Any) -> Decimal:
    quantity = Decimal(str(position.quantity))
    return quantity if position.side == PositionSide.LONG else -quantity


def _index_of(contract: CryptoOption, code: str) -> InstrumentId:
    """The index of the underlying ``code`` on the contract's venue."""
    return underlying_index(code, contract.id.venue.value)


def _weighted(
    holding: Holding, indexes: Mapping[InstrumentId, float], betas: Mapping[str, float]
) -> float:
    code = holding.contract.underlying.code
    own = _index_of(holding.contract, code)
    base = _index_of(holding.contract, BASE)
    ratio = 1.0 if own == base else indexes[own] / indexes[base]
    return float(holding.quantity) * holding.delta * ratio * betas.get(code, 1.0)
