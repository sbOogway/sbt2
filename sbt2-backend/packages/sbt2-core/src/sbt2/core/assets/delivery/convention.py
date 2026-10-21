from collections.abc import Iterable
from datetime import date, datetime
from typing import Any, override

from nautilus_trader.model import IndexPriceUpdate, InstrumentId

from sbt2.core.assets.conventions.settlement import SettlementConvention
from sbt2.core.assets.delivery.prices import delivery_id, expires_within, expiry_day
from sbt2.data import Selection, Window


class DeliverySettlement(SettlementConvention):
    """A contract expires at the delivery price of its expiry day."""

    @override
    def delivery_selections(
        self, instruments: Iterable[Any], window: tuple[datetime, datetime]
    ) -> list[Selection]:
        expiring = {
            (delivery_id(each), expiry_day(each))
            for each in instruments
            if expires_within(each, window)
        }
        return [
            Selection((series,), (IndexPriceUpdate,), Window.of_days(day, day))
            for series, day in sorted(expiring, key=_order)
        ]


def _order(delivery: tuple[InstrumentId, date]) -> tuple[str, date]:
    return str(delivery[0]), delivery[1]
