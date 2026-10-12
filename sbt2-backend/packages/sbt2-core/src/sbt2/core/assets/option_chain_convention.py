from collections.abc import Mapping
from datetime import datetime
from typing import Any, override

from nautilus_trader.model import IndexPriceUpdate, InstrumentId

from sbt2.core.assets.base import ChainConvention, ChainJob
from sbt2.core.assets.option_chain import ChainBand, dvol_of, index_of, is_chain
from sbt2.core.assets.option_chain_selection import select_contracts
from sbt2.data import Selection, Window


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

    @override
    def contracts(self, job: ChainJob) -> list[InstrumentId]:
        return select_contracts(job)

    @override
    def days(self, chain: InstrumentId, window: tuple[datetime, datetime]) -> Selection:
        """The index: ingesting a day of the underlying brings its index prices."""
        return Selection((index_of(chain),), (IndexPriceUpdate,), Window(*window))

    @override
    def references(
        self, chain: InstrumentId, window: tuple[datetime, datetime]
    ) -> list[Selection]:
        return [Selection((dvol_of(chain),), (IndexPriceUpdate,), Window(*window))]
