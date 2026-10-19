from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
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
from sbt2.core.assets.option_delivery import (
    delivery_id,
    delivery_price,
    expires_within,
)
from sbt2.core.assets.option_quotes import OptionHistory, QuoteSettings, quote_ticks
from sbt2.core.assets.option_settlement import settlement_price, settlement_quotes
from sbt2.core.market import index_id
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
        self._deliveries: dict[tuple[InstrumentId, int], Decimal] = {}
        self.contracts = list(self._catalog.instruments(job.instruments).values())
        target.write_instruments(self.contracts)
        self._marks = _frames(
            self._catalog, (self.contracts, MarkPriceUpdate), job.window
        )
        self._greeks = _frames(
            self._catalog, (self.contracts, OptionGreeks), job.window
        )

    def write(self, contract: CryptoOption) -> bool:
        """Write the contract's quotes; whether it has any."""
        history = OptionHistory(
            contract,
            self._marks[contract.id],
            self._greeks[contract.id],
            self._index(index_id(contract)),
        )
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
        delivery = self._delivery(contract)
        return settlement_quotes(contract, settlement_price(contract, delivery))

    def _delivery(self, contract: CryptoOption) -> Decimal:
        """The delivery price, read once for all contracts of an expiry."""
        key = (delivery_id(contract), contract.expiration_ns)
        if key not in self._deliveries:
            self._deliveries[key] = delivery_price(self._catalog, contract)
        return self._deliveries[key]

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


def _frames(
    catalog: Catalog, series: tuple[list[CryptoOption], type], span: Span
) -> dict[InstrumentId, pd.DataFrame]:
    """Each contract's records from the day before ``span`` on, with the last one
    before the span: the quotes need no more. When none of a contract's records is
    before the span, the last one is older: read from the contract's activation."""
    contracts, kind = series
    start, end = span
    first = _day_start(start) - timedelta(days=1)
    frames = _since_activation(catalog, (contracts, kind), Window(first, end))
    stale = [
        each
        for each in contracts
        if _activation(each) < first and not (frames[each.id].index < start).any()
    ]
    if stale:
        since = min(_activation(each) for each in stale)
        frames |= _since_activation(catalog, (stale, kind), Window(since, end))
    return frames


def _since_activation(
    catalog: Catalog, series: tuple[list[CryptoOption], type], window: Window
) -> dict[InstrumentId, pd.DataFrame]:
    """The contracts' records in ``window``, none before a contract's activation."""
    contracts, kind = series
    frames = catalog.frames([each.id for each in contracts], kind, window)
    return {each.id: _active(frames[each.id], each) for each in contracts}


def _active(frame: pd.DataFrame, contract: CryptoOption) -> pd.DataFrame:
    return frame.loc[frame.index >= _activation(contract)]


def _day_start(moment: datetime) -> datetime:
    return moment.replace(hour=0, minute=0, second=0, microsecond=0)


def _activation(contract: CryptoOption) -> datetime:
    return _moment(contract.activation_ns)


def _moment(nanos: int) -> datetime:
    return datetime.fromtimestamp(nanos / 1e9, UTC)


def _index_on_grid(
    catalog: Catalog, index_id: InstrumentId, grid: tuple[Span, QuoteSettings]
) -> pd.Series:
    """The index price the grid times carry: the last update up to each of them,
    from the day before the span on."""
    (start, end), settings = grid
    step = f"{settings.interval_seconds}s"
    days = Window(start - timedelta(days=1), end).days
    frame = catalog.frame(index_id, IndexPriceUpdate, Window.of_days(days[0], days[-1]))
    # Grid each day on its own: a day without updates adds no grid times.
    on_grid = [_on_grid(_of_day(frame, day), step) for day in days]
    carried = pd.concat(on_grid).groupby(level=0).last().ffill().dropna()
    return pd.Series(carried)


def _of_day(frame: pd.DataFrame, day: date) -> pd.DataFrame:
    window = Window.of_days(day, day)
    return frame.loc[(frame.index >= window.start) & (frame.index < window.end)]


def _on_grid(frame: pd.DataFrame, step: str) -> pd.Series:
    return (
        frame["price"]
        .resample(step, closed="right", label="right", origin="epoch")
        .last()
    )
