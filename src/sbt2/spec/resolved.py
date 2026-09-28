from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
)

from sbt2.assets import AssetProfile
from sbt2.spec.canonical import canonical_hash
from sbt2.spec.venues import venue_objects
from sbt2.strategy import StrategyRun


@dataclass(frozen=True)
class ResolvedRunSpec:
    """A run spec with every name replaced by what it stands for.

    ``venue`` and ``data`` are nautilus's own ``BacktestVenueConfig`` and
    ``BacktestDataConfig`` arguments as plain data, without the catalog path.
    """

    strategy: StrategyRun
    asset: AssetProfile
    venue: Mapping[str, Any]
    data: Sequence[Mapping[str, Any]]
    equity_interval_ms: int
    start: datetime
    end: datetime

    @property
    def hash(self) -> str:
        return canonical_hash(self._document())

    def run_config(self, catalog_path: str, **machine: Any) -> BacktestRunConfig:
        """The nautilus run config, reading data from ``catalog_path``.

        ``machine`` holds ``BacktestRunConfig`` arguments that never change the
        results, such as ``chunk_size``; like the catalog path, they are not hashed.
        """
        return BacktestRunConfig(
            [BacktestVenueConfig(**venue_objects(self.venue))],
            [
                BacktestDataConfig(catalog_path=catalog_path, **arguments)
                for arguments in self.data
            ],
            engine=BacktestEngineConfig(
                portfolio=self.asset.portfolio_config(self.equity_interval_ms)
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
            "start": self.start,
            "end": self.end,
        }
