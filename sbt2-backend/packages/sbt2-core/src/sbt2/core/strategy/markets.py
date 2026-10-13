from collections.abc import Callable, Iterator, Mapping, Sequence

from nautilus_trader.model import IndexPriceUpdate, InstrumentId, OptionGreeks

from sbt2.core.market import ChainFeeds
from sbt2.core.strategy.chain import CachedChain, ChainCache, MultipleChainsError
from sbt2.core.strategy.chain_records import ChainHistory, ChainRecords


class Markets:
    """What a run heard of the market of each chain it streams, by the code of
    the underlying: the records of the chain, which its feeds and the IV of its
    contracts fill."""

    def __init__(self, feeds: Sequence[ChainFeeds], now_ns: Callable[[], int]) -> None:
        self._feeds = tuple(feeds)
        self._records = {each.underlying: ChainRecords(now_ns) for each in feeds}
        self._silent = ChainRecords(now_ns)

    @property
    def feeds(self) -> tuple[ChainFeeds, ...]:
        return self._feeds

    def series(self) -> Iterator[InstrumentId]:
        """The index and the volatility index of each chain, to subscribe to."""
        for feed in self._feeds:
            yield from (feed.index, feed.volatility)

    def first(self) -> ChainRecords:
        """The records of the first chain; empty when the run streams none."""
        return next(iter(self._records.values()), self._silent)

    def only(self) -> ChainRecords:
        """The records of the one chain of the run; empty when it streams none,
        ``MultipleChainsError`` when it streams several."""
        if len(self._records) > 1:
            raise MultipleChainsError(
                f"the run streams the chains {', '.join(self._records)}; "
                "ask for one from `chains`"
            )
        return self.first()

    def chains(
        self, cache: ChainCache, instrument_ids: Sequence[InstrumentId]
    ) -> dict[str, CachedChain]:
        """The chain of each underlying, over its own contracts among
        ``instrument_ids`` and its own records."""
        return {
            code: CachedChain(
                cache,
                [each for each in instrument_ids if _underlying(each) == code],
                records,
            )
            for code, records in self._records.items()
        }

    def indexes(self) -> dict[InstrumentId, float]:
        """The latest index price of each chain that has heard one."""
        latest = {
            feed.index: self._records[feed.underlying].index() for feed in self._feeds
        }
        return {index: price for index, price in latest.items() if price is not None}

    def prices(self) -> dict[str, float]:
        """The latest index price of each chain that has heard one, by the code
        of its underlying."""
        latest = {
            feed.underlying: self._records[feed.underlying].index()
            for feed in self._feeds
        }
        return {code: price for code, price in latest.items() if price is not None}

    def preload(self, histories: Mapping[str, ChainHistory]) -> None:
        """Hear what each chain knew before the run, by underlying."""
        for code, history in histories.items():
            self._records[code].preload(history)

    def hear_index_price(self, event: IndexPriceUpdate) -> None:
        for feed in self._feeds:
            records = self._records[feed.underlying]
            if event.instrument_id == feed.volatility:
                records.hear_volatility(event.ts_event, float(event.value))
            elif event.instrument_id == feed.index:
                records.hear_index(event.ts_event, float(event.value))

    def hear_greeks(self, greeks: OptionGreeks) -> None:
        records = self._records.get(_underlying(greeks.instrument_id))
        if records is not None and greeks.mark_iv is not None:
            records.hear_iv(greeks.instrument_id, greeks.ts_event, greeks.mark_iv)


def _underlying(contract: InstrumentId) -> str:
    """The code a contract's symbol starts with, such as ``BTC``."""
    return contract.symbol.value.partition("-")[0]
