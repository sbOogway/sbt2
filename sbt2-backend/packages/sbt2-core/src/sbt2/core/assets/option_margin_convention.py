from collections.abc import Mapping
from typing import Any, override

from sbt2.core.assets.base import MarginConvention
from sbt2.core.assets.option_margin import MarginRates


class OptionMargin(MarginConvention):
    """sbt2 margins an option as Deribit's standard margin does; its ``margin``
    setting holds the rates."""

    @override
    def complete(self, venue: Mapping[str, Any]) -> dict[str, Any]:
        rates = MarginRates.from_table(venue.get("margin", {}))
        return {
            **venue,
            "margin": {
                "base_rate": f"{rates.base_rate:f}",
                "floor_rate": f"{rates.floor_rate:f}",
                "maintenance_rate": f"{rates.maintenance_rate:f}",
            },
        }
