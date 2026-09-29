import copyreg
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.model import NautilusDataType

from sbt2.assets import AssetProfile
from sbt2.spec.resolve.canonical import canonical_hash, canonical_json
from sbt2.spec.resolve.venues import venue_objects
from sbt2.spec.split import Splitter
from sbt2.strategy import StrategyRun


@dataclass(frozen=True)
class ResolvedRunSpec:
    """A run spec with every name replaced by what it stands for.

    ``venue`` and ``data`` are nautilus's own ``BacktestVenueConfig`` and
    ``BacktestDataConfig`` arguments as plain data, without the catalog path.
    ``source`` names where missing data is fetched from; like the catalog path,
    it is not hashed. ``start`` and ``end`` are the dates of ``part``.
    """

    strategy: StrategyRun
    asset: AssetProfile
    source: str
    venue: Mapping[str, Any]
    data: Sequence[Mapping[str, Any]]
    equity_interval_ms: int
    split: Splitter
    part: str
    start: datetime
    end: datetime

    @property
    def hash(self) -> str:
        return canonical_hash(self._document())

    def to_json(self) -> str:
        """The canonical JSON the hash is taken of."""
        return canonical_json(self._document())

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
                **(engine or {}),
            ),
            start=self.start,
            end=self.end,
            **machine,
        )

    def _document(self) -> dict[str, Any]:
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


def _data_type_by_name(
    data_type: NautilusDataType,
) -> tuple[Callable[..., NautilusDataType], tuple[type, str]]:
    """Nautilus's enums don't pickle; they come back by their name."""
    return getattr, (NautilusDataType, str(data_type))


copyreg.pickle(NautilusDataType, _data_type_by_name)
