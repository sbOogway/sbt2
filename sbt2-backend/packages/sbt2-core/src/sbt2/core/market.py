from dataclasses import dataclass

from nautilus_trader.model import CryptoOption, InstrumentId


@dataclass(frozen=True)
class ChainFeeds:
    """The series a chain strategy hears besides the contracts: the ``index`` the
    contracts are priced on and the ``volatility`` index of the underlying."""

    index: InstrumentId
    volatility: InstrumentId


def underlying_index(code: str, venue: str) -> InstrumentId:
    """The id of the USD index of the underlying ``code`` on ``venue``."""
    return InstrumentId.from_str(f"{code}_USD.{venue}")


def index_id(contract: CryptoOption) -> InstrumentId:
    """The id of the series of index prices the contract's underlying has."""
    return underlying_index(contract.underlying.code, contract.id.venue.value)
