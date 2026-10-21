from collections.abc import Iterable, Mapping
from datetime import date, datetime
from typing import Any, override

from nautilus_trader.model import IndexPriceUpdate, InstrumentId

from sbt2.core.assets.conventions.settlement import SettlementConvention
from sbt2.core.assets.option.settlement.delivery import (
    delivery_id,
    expires_within,
    expiry_day,
)
from sbt2.core.assets.option.settlement.delivery_fee_model import DeliveryFeeModel
from sbt2.core.assets.option.settlement.settlement import DeliveryFee
from sbt2.data import Selection, Window


class OptionSettlement(SettlementConvention):
    """An option expires at the delivery price; its ``delivery_fee`` setting holds
    the rates of the fee."""

    @override
    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        fee = DeliveryFee.from_table(venue.get("delivery_fee", {}))
        rates = {"rate": f"{fee.rate:f}", "cap_rate": f"{fee.cap_rate:f}"}
        return {**venue, "delivery_fee": rates}

    @override
    def fee_model(self, base: Any, venue: Mapping[str, Any], tag: str) -> Any:
        fee = DeliveryFee.from_table(venue["delivery_fee"])
        return DeliveryFeeModel(base, fee, tag)

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
