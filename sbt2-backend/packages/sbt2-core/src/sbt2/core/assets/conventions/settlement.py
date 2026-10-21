from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from sbt2.data import Selection


class SettlementConvention(ABC):
    """How the venue settles a position at its contract's expiry."""

    @abstractmethod
    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        """The venue arguments with the settlement settings filled in with their
        defaults; ``ValueError`` when the settings are invalid."""
        ...

    @abstractmethod
    def fee_model(self, base: Any, venue: Mapping[str, Any], tag: str) -> Any:
        """The venue's fee model ``base``, or none, made to charge the fee of a
        settlement on the orders tagged ``tag``, which close the positions of
        an expired contract."""
        ...

    @abstractmethod
    def delivery_selections(
        self, instruments: Iterable[Any], window: tuple[datetime, datetime]
    ) -> list[Selection]:
        """The delivery data a run of ``instruments`` over ``window`` settles at."""
        ...


class NoSettlement(SettlementConvention):
    """The instruments never expire."""

    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        if "delivery_fee" in venue:
            raise ValueError("this asset class takes no delivery_fee setting")
        return dict(venue)

    def fee_model(self, base: Any, venue: Mapping[str, Any], tag: str) -> Any:
        del venue, tag
        return base

    def delivery_selections(
        self, instruments: Iterable[Any], window: tuple[datetime, datetime]
    ) -> list[Selection]:
        del instruments, window
        return []
