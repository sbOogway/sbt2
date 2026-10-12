from collections.abc import Mapping
from typing import Any, override

from nautilus_trader.model import InstrumentId

from sbt2.core.assets.base import ChainConvention
from sbt2.core.assets.option_chain import ChainBand, is_chain


class OptionChain(ChainConvention):
    """An instrument such as ``BTC-OPTIONS.DERIBIT`` names every option of its
    underlying; the spec's ``chain`` table sets the bands of the contracts the run
    loads."""

    @override
    def names_chain(self, instrument_id: InstrumentId) -> bool:
        return is_chain(instrument_id)

    @override
    def complete(self, table: Mapping[str, Any]) -> dict[str, Any]:
        return ChainBand.from_table(table).to_table()
