from collections.abc import Mapping
from typing import Any, override

from sbt2.core.assets.base import SettlementConvention
from sbt2.core.assets.delivery_fee_model import DeliveryFeeModel
from sbt2.core.assets.option_settlement import DeliveryFee


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
