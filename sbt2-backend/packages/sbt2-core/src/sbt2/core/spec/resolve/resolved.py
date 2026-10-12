from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import nautilus_trader.model
from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.model import InstrumentId, Money, NautilusDataType
from nautilus_trader.risk import RiskEngineConfig

from sbt2.core.assets import AssetProfile, ChainFeeds, ChainJob, QuoteJob
from sbt2.core.spec.resolve.canonical import canonical_hash, canonical_json
from sbt2.core.spec.resolve.data import data_arguments
from sbt2.core.spec.resolve.document import spec_fields
from sbt2.core.spec.resolve.models import venue_objects
from sbt2.core.spec.split import Splitter
from sbt2.core.strategy import SETTLEMENT_TAG, StrategyRun
from sbt2.data import Catalog


@dataclass(frozen=True)
class Study:
    """The study a run belongs to, and the context it fixes: every key of the
    spec file but ``params``, ``part`` and ``study``, as JSON."""

    name: str
    context: Mapping[str, Any]


@dataclass(frozen=True)
class ResolvedRunSpec:
    """A run spec with every name replaced by what it stands for.

    ``venue`` and ``data`` are nautilus's own ``BacktestVenueConfig`` and
    ``BacktestDataConfig`` arguments as plain data, without the catalog path.
    ``source`` names where missing data is fetched from; like the catalog path,
    it is neither hashed nor compared, and a spec rebuilt from its document has
    none. ``start`` and ``end`` are the dates of ``part``.
    ``risk`` holds nautilus's ``RiskEngineConfig`` arguments. With the
    strategy's drawdown limit it enters the hashed document only when set, so
    a run without either keeps its hash.
    ``chain`` holds the bands of the chains the strategy's instruments name, and
    enters the hashed document only when set.
    ``lookback`` is how far before the data window the volatility index of a
    chain is loaded; the strategy sets it and it is not hashed.
    ``study``, like ``source``, is neither hashed nor compared: the same
    backtest has the same hash in or out of a study.
    """

    strategy: StrategyRun
    asset: AssetProfile
    source: str = field(compare=False)
    venue: Mapping[str, Any]
    data: Sequence[Mapping[str, Any]]
    equity_interval_ms: int
    split: Splitter
    part: str
    start: datetime
    end: datetime
    risk: Mapping[str, Any] = field(default_factory=dict)
    chain: Mapping[str, Any] = field(default_factory=dict)
    lookback: timedelta = timedelta(0)
    study: Study | None = field(default=None, compare=False)

    @classmethod
    def from_document(
        cls, document: Mapping[str, Any], strategy_source: Path | None = None
    ) -> ResolvedRunSpec:
        """The spec whose hashed document ``document`` is, as ``to_json`` wrote it.

        With ``strategy_source``, the strategy's module is imported from that file."""
        return cls(source="", **spec_fields(document, strategy_source))

    @property
    def hash(self) -> str:
        return canonical_hash(self._document())

    def to_json(self) -> str:
        """The canonical JSON the hash is taken of."""
        return canonical_json(self._document())

    @property
    def venue_name(self) -> str:
        return self.venue["name"]

    @property
    def currency(self) -> str:
        """The settlement currency of the starting balance."""
        [balance] = self.venue["starting_balances"]
        return Money.from_str(balance).currency.code

    @property
    def liquidation_enabled(self) -> bool:
        return bool(self.venue.get("liquidation_enabled"))

    @property
    def data_types(self) -> tuple[type, ...]:
        """The nautilus data classes the run streams."""
        return tuple(
            getattr(nautilus_trader.model, str(each["data_type"])) for each in self.data
        )

    @property
    def _data_types(self) -> list[NautilusDataType]:
        return [each["data_type"] for each in self.data]

    @property
    def instrument_ids(self) -> tuple[InstrumentId, ...]:
        return tuple(self._first_data["instrument_ids"])

    @property
    def data_window(self) -> tuple[datetime, datetime]:
        """The span the data is read over, the strategy's warm-up included."""
        first = self._first_data
        return first["start_time"], first["end_time"]

    def with_contracts(self, catalog: Catalog) -> ResolvedRunSpec:
        """The spec with each chain its instruments name replaced by the contracts
        of ``catalog`` inside the chain's bands, in the strategy and the data."""
        named = self.instrument_ids
        if not self.chains:
            return self
        members = dict.fromkeys(
            member for each in named for member in self._members(each, catalog)
        )
        instruments = list(members)
        feeds = self.asset.chain.feeds(self.chains[0])
        return replace(
            self,
            strategy=replace(
                self.strategy,
                instruments=instruments,
                index=feeds.index,
                volatility=feeds.volatility,
            ),
            data=[
                *data_arguments(self._data_types, instruments, self.data_window),
                *self._feed_data(feeds),
            ],
        )

    @property
    def volatility_window(self) -> tuple[datetime, datetime]:
        """The span the volatility index is read over: the data window and the
        strategy's look-back before it."""
        start, end = self.data_window
        return start - self.lookback, end

    def _feed_data(self, feeds: ChainFeeds) -> list[Mapping[str, Any]]:
        kinds = [NautilusDataType.IndexPriceUpdate]
        return data_arguments(kinds, [feeds.index, feeds.volatility], self.data_window)

    @property
    def chains(self) -> tuple[InstrumentId, ...]:
        """The chains the strategy's instruments name."""
        return tuple(
            each for each in self.instrument_ids if self.asset.chain.names_chain(each)
        )

    def contracts_of(self, chain: InstrumentId, catalog: Catalog) -> list[InstrumentId]:
        """The contracts of ``chain`` that ``catalog`` holds inside its bands."""
        job = ChainJob(catalog, chain, self.data_window, self.chain)
        return self.asset.chain.contracts(job)

    def _members(
        self, instrument_id: InstrumentId, catalog: Catalog
    ) -> list[InstrumentId]:
        if instrument_id not in self.chains:
            return [instrument_id]
        return self.contracts_of(instrument_id, catalog)

    def quote_job(self, catalog: Path) -> QuoteJob:
        """What the quotes made at run time are made from."""
        return QuoteJob(catalog, self.instrument_ids, self.data_window, self.venue)

    def split_json(self) -> str:
        """The split's canonical JSON, as it appears in the hashed document."""
        return canonical_json(self.split.document())

    def run_config(
        self,
        catalog_path: str,
        engine: Mapping[str, Any] | None = None,
        quotes: Sequence[BacktestDataConfig] = (),
        **machine: Any,
    ) -> BacktestRunConfig:
        """The nautilus run config, reading data from ``catalog_path``.

        ``engine`` and ``machine`` hold ``BacktestEngineConfig`` and
        ``BacktestRunConfig`` arguments that never change the results, such as
        ``logging`` or ``chunk_size``; like the catalog path, they are not hashed.
        ``quotes`` stream the quotes made at run time.
        """
        return BacktestRunConfig(
            [self._venue_config()],
            [
                *(
                    BacktestDataConfig(catalog_path=catalog_path, **arguments)
                    for arguments in self.data
                ),
                *quotes,
            ],
            engine=BacktestEngineConfig(
                portfolio=self.asset.portfolio_config(self.equity_interval_ms),
                risk_engine=RiskEngineConfig(**self.risk),
                **(engine or {}),
            ),
            start=self.start,
            end=self.end,
            **machine,
        )

    def _venue_config(self) -> BacktestVenueConfig:
        objects = venue_objects(self.venue)
        fee_model = self.asset.settlement.fee_model(
            objects.get("fee_model"), self.venue, SETTLEMENT_TAG
        )
        if fee_model is not None:
            objects["fee_model"] = fee_model
        return BacktestVenueConfig(**objects)

    @property
    def _first_data(self) -> Mapping[str, Any]:
        """Every data type is read for the same instruments over the same window."""
        [first, *_] = self.data
        return first

    def _document(self) -> dict[str, Any]:
        document = self._core_document()
        risk = self._risk_document()
        if risk:
            document["risk"] = risk
        if self.chain:
            document["chain"] = dict(self.chain)
        return document

    def _risk_document(self) -> dict[str, Any]:
        limit = self.strategy.drawdown_limit
        drawdown = {} if limit is None else {"drawdown_limit": limit}
        return {**self.risk, **drawdown}

    def _core_document(self) -> dict[str, Any]:
        return {
            "strategy": {
                "path": self.strategy.strategy,
                "instruments": list(self.strategy.instruments),
                "params": dict(self.strategy.params),
                "trade_start": self.strategy.trade_start,
            },
            "asset_class": self.asset.asset_class,
            "instrument_class": self.asset.instrument_class,
            "venue": dict(self.venue),
            "data": [dict(arguments) for arguments in self.data],
            "equity_interval_ms": self.equity_interval_ms,
            "split": self.split.document(),
            "part": self.part,
            "start": self.start,
            "end": self.end,
        }
