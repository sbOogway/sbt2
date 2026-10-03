from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import nautilus_trader.model
from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.model import InstrumentId, Money
from nautilus_trader.risk import RiskEngineConfig

from sbt2.core.assets import AssetProfile
from sbt2.core.spec.resolve.canonical import canonical_hash, canonical_json
from sbt2.core.spec.resolve.document import spec_fields
from sbt2.core.spec.resolve.models import venue_objects
from sbt2.core.spec.split import Splitter
from sbt2.core.strategy import StrategyRun


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
    study: Study | None = field(default=None, compare=False)

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> ResolvedRunSpec:
        """The spec whose hashed document ``document`` is, as ``to_json`` wrote it."""
        return cls(source="", **spec_fields(document))

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
    def instrument_ids(self) -> tuple[InstrumentId, ...]:
        return tuple(self._first_data["instrument_ids"])

    @property
    def data_window(self) -> tuple[datetime, datetime]:
        """The span the data is read over, the strategy's warm-up included."""
        first = self._first_data
        return first["start_time"], first["end_time"]

    def split_json(self) -> str:
        """The split's canonical JSON, as it appears in the hashed document."""
        return canonical_json(self.split.document())

    def run_config(
        self,
        catalog_path: str,
        engine: Mapping[str, Any] | None = None,
        **machine: Any,
    ) -> BacktestRunConfig:
        """The nautilus run config, reading data from ``catalog_path``.

        ``engine`` and ``machine`` hold ``BacktestEngineConfig`` and
        ``BacktestRunConfig`` arguments that never change the results, such as
        ``logging`` or ``chunk_size``; like the catalog path, they are not hashed.
        """
        return BacktestRunConfig(
            [BacktestVenueConfig(**venue_objects(self.venue))],
            [
                BacktestDataConfig(catalog_path=catalog_path, **arguments)
                for arguments in self.data
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
