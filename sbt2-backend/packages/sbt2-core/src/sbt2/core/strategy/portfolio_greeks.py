from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from nautilus_trader.model import CryptoOption, InstrumentId

BETA = 1.0


@dataclass(frozen=True)
class Holding:
    """An open position: ``quantity`` is signed, ``delta`` is the contract's own,
    per contract."""

    contract: CryptoOption
    quantity: Decimal
    delta: float


def beta_weighted_delta(
    holdings: Sequence[Holding], indexes: Mapping[InstrumentId, float]
) -> float:
    """The delta of ``holdings`` in BTC: each position's delta times its
    underlying index over the BTC index and its beta, which is 1 for every
    underlying. ``KeyError`` when a position needs an index price missing from
    ``indexes``."""
    return sum((_weighted(each, indexes) for each in holdings), 0.0)


def _weighted(holding: Holding, indexes: Mapping[InstrumentId, float]) -> float:
    contract = holding.contract
    venue = contract.id.venue.value
    own = InstrumentId.from_str(f"{contract.underlying.code}_USD.{venue}")
    base = InstrumentId.from_str(f"BTC_USD.{venue}")
    ratio = 1.0 if own == base else indexes[own] / indexes[base]
    return float(holding.quantity) * holding.delta * ratio * BETA
