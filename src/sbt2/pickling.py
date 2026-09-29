"""The pickle reducers a batch needs to send an order to its child.

Nautilus's enums don't pickle, so each comes back by its name, and an asset
profile comes back as the registered one for its classes.
"""

import copyreg
from collections.abc import Callable
from typing import Any

from nautilus_trader.common import LogLevel
from nautilus_trader.model import (
    AccountType,
    AssetClass,
    InstrumentClass,
    NautilusDataType,
    OmsType,
)

from sbt2.assets import AssetProfile, asset_profile

__all__ = ["register"]


def register() -> None:
    """Register every reducer; calling it again changes nothing."""
    for enum in (AssetClass, InstrumentClass, OmsType, AccountType):
        copyreg.pickle(enum, _by_name)
    copyreg.pickle(NautilusDataType, _data_type_by_name)
    copyreg.pickle(LogLevel, _level_by_name)
    copyreg.pickle(AssetProfile, _by_classes)


def _by_name(value: Any) -> tuple[Callable[..., Any], tuple[type, str]]:
    return getattr, (type(value), value.name)


def _data_type_by_name(
    data_type: NautilusDataType,
) -> tuple[Callable[..., NautilusDataType], tuple[type, str]]:
    return getattr, (NautilusDataType, str(data_type))


def _level_by_name(level: LogLevel) -> tuple[Callable[..., LogLevel], tuple[str]]:
    return LogLevel.from_str, (level.name,)


def _by_classes(
    profile: AssetProfile,
) -> tuple[Callable[..., AssetProfile], tuple[AssetClass, InstrumentClass]]:
    return asset_profile, (profile.asset_class, profile.instrument_class)
