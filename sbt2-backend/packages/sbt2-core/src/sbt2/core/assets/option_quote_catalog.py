from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
from nautilus_trader.model import (
    CryptoOption,
    IndexPriceUpdate,
    InstrumentId,
    MarkPriceUpdate,
    OptionGreeks,
    QuoteTick,
)
from nautilus_trader.persistence import ParquetDataCatalog

from sbt2.core.assets.base import QuoteJob
from sbt2.core.assets.option_delivery import delivery_price, expires_within, index_id
from sbt2.core.assets.option_quotes import OptionHistory, QuoteSettings, quote_ticks
from sbt2.core.assets.option_settlement import settlement_price, settlement_quotes
from sbt2.data import Catalog, Window

type Span = tuple[datetime, datetime]


class NoQuotesError(LookupError):
    pass


def write_quotes(
    job: QuoteJob, settings: QuoteSettings, folder: Path
) -> list[InstrumentId]:
    """Write the quotes of each contract of ``job`` that has any to a catalog in
    ``folder``, and return their ids."""
    quoter = _Quoter(job, settings, ParquetDataCatalog(str(folder)))
    quoted = [each.id for each in quoter.contracts if quoter.write(each)]
    if not quoted:
        raise NoQuotesError(_no_quotes(job))
    return quoted


class _Quoter:
    def __init__(
        self, job: QuoteJob, settings: QuoteSettings, target: ParquetDataCatalog
    ) -> None:
        self._job = job
        self._settings = settings
        self._target = target
        self._catalog = Catalog(job.catalog)
        self._indexes: dict[InstrumentId, pd.Series] = {}
        self.contracts = list(self._catalog.instruments(job.instruments).values())
        target.write_instruments(self.contracts)

    def write(self, contract: CryptoOption) -> bool:
        """Write the contract's quotes; whether it has any."""
        index = self._index(index_id(contract))
        history = _history(self._catalog, contract, (self._job.window[1], index))
        quotes = quote_ticks(history, self._settings, self._job.window)
        if quotes:
            quotes += self._settlement(contract)
            self._target.write_quote_ticks(
                quotes, quotes[0].ts_event, quotes[-1].ts_event
            )
        return bool(quotes)

    def _settlement(self, contract: CryptoOption) -> list[QuoteTick]:
        """The closing quotes of a contract that expires within the run."""
        if not expires_within(contract, self._job.window):
            return []
        delivery = delivery_price(self._catalog, contract)
        return settlement_quotes(contract, settlement_price(contract, delivery))

    def _index(self, index_id: InstrumentId) -> pd.Series:
        if index_id not in self._indexes:
            self._indexes[index_id] = _index_on_grid(
                self._catalog, index_id, (self._job.window, self._settings)
            )
        return self._indexes[index_id]


def _no_quotes(job: QuoteJob) -> str:
    ids = ", ".join(str(each) for each in job.instruments)
    return (
        f"no quotes can be made for {ids} from {job.window[0]} to {job.window[1]}: "
        "the catalog lacks their marks, IV records or the index"
    )


def _history(
    catalog: Catalog, contract: CryptoOption, until: tuple[datetime, pd.Series]
) -> OptionHistory:
    end, index = until
    window = Window(_moment(contract.activation_ns), end)
    return OptionHistory(
        contract,
        catalog.frame(contract.id, MarkPriceUpdate, window),
        catalog.frame(contract.id, OptionGreeks, window),
        index,
    )


def _moment(nanos: int) -> datetime:
    return datetime.fromtimestamp(nanos / 1e9, UTC)


def _index_on_grid(
    catalog: Catalog, index_id: InstrumentId, grid: tuple[Span, QuoteSettings]
) -> pd.Series:
    """The index price the grid times carry: the last update up to each of them,
    from the day before the span on."""
    (start, end), settings = grid
    step = f"{settings.interval_seconds}s"
    days = [
        _on_grid(
            catalog.frame(index_id, IndexPriceUpdate, Window.of_days(day, day)), step
        )
        for day in Window(start - timedelta(days=1), end).days
    ]
    carried = pd.concat(days).groupby(level=0).last().ffill().dropna()
    return pd.Series(carried)


def _on_grid(frame: pd.DataFrame, step: str) -> pd.Series:
    return (
        frame["price"]
        .resample(step, closed="right", label="right", origin="epoch")
        .last()
    )
