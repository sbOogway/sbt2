from collections.abc import Sequence
from datetime import datetime
from typing import Any

from nautilus_trader.backtest import BacktestDataConfig, BacktestVenueConfig
from nautilus_trader.execution import FixedFeeModel
from nautilus_trader.model import (
    AccountType,
    InstrumentId,
    Money,
    NautilusDataType,
    OmsType,
)

from sbt2.core.spec.resolve.data import data_arguments

_NO_FEE = FixedFeeModel(Money.from_str("0 USDT"), None)


def feed_data(
    feeds: Sequence[InstrumentId], catalog: str, window: tuple[datetime, datetime]
) -> list[BacktestDataConfig]:
    """The run's reading of the feeds' 1-minute candles over ``window``."""
    if not feeds:
        return []
    return [
        BacktestDataConfig(catalog_path=catalog, **arguments)
        for arguments in data_arguments([NautilusDataType.Bar], feeds, window)
    ]


def feed_venues(
    feeds: Sequence[InstrumentId], traded: str
) -> list[BacktestVenueConfig]:
    """A venue with nothing to trade for each venue of the feeds other than
    ``traded``: nautilus streams the data of an instrument only on a venue it
    has."""
    names = dict.fromkeys(
        each.venue.value for each in feeds if each.venue.value != traded
    )
    return [_data_only(name) for name in names]


def _data_only(name: str) -> BacktestVenueConfig:
    arguments: dict[str, Any] = {
        "name": name,
        "oms_type": OmsType.NETTING,
        "account_type": AccountType.MARGIN,
        "starting_balances": ["0 USDT"],
        "fee_model": _NO_FEE,
    }
    return BacktestVenueConfig(**arguments)
