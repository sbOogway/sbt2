from pathlib import Path
from typing import override

from nautilus_trader.backtest import BacktestDataConfig
from nautilus_trader.model import NautilusDataType
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.core.assets.conventions.quotes import QuoteJob
from sbt2.core.assets.delivery.prices import delivery_price, expires_within
from sbt2.core.assets.delivery.quotes import settlement_quotes
from sbt2.core.assets.marks import Marks
from sbt2.data import Catalog


class FutureQuotes(Marks):
    """The marks of a dated future and, when it expires within the run, the quotes
    of its delivery price at the expiry, where its positions settle."""

    @override
    def write(self, job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
        return [*super().write(job, folder), *_write_settlement(job, folder)]


def _write_settlement(job: QuoteJob, folder: Path) -> list[BacktestDataConfig]:
    catalog = Catalog(job.catalog)
    contracts = catalog.instruments(job.instruments).values()
    expiring = [each for each in contracts if expires_within(each, job.window)]
    if not expiring:
        return []
    target = ParquetDataCatalog(str(folder))
    target.write_instruments(expiring)
    for contract in expiring:
        quotes = settlement_quotes(contract, delivery_price(catalog, contract))
        target.write_quote_ticks(quotes, quotes[0].ts_event, quotes[-1].ts_event)
    start, end = job.window
    return [
        BacktestDataConfig(
            catalog_path=str(folder),
            data_type=NautilusDataType.QuoteTick,
            instrument_ids=[each.id for each in expiring],
            start_time=start,
            end_time=end,
        )
    ]
