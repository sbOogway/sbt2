from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.model import (
    BarSpecification,
    InstrumentId,
    NautilusDataType,
    PriceType,
    QuoteTick,
    TradeTick,
)

from sbt2.assets import AssetProfile
from sbt2.spec.canonical import canonical_hash
from sbt2.spec.parse import RunSpec
from sbt2.spec.venues import venue_objects, venue_profile
from sbt2.strategy import StrategyRun, import_strategy, resolve_params


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


class InstrumentVenueError(ValueError):
    pass


def resolve(spec: RunSpec, venue_profiles: Path) -> ResolvedRunSpec:
    asset, venue = venue_profile(venue_profiles, spec.venue)
    instruments = _instruments(spec.instruments, venue["name"])
    strategy = import_strategy(spec.strategy)
    params = resolve_params(strategy, spec.params)
    data_start = spec.start - strategy.warmup(params)
    return ResolvedRunSpec(
        strategy=StrategyRun(spec.strategy, instruments, asdict(params), spec.start),
        asset=asset,
        venue=_seeded({**venue, "starting_balances": [spec.capital]}, spec.seed),
        data=_data(
            _data_types(strategy.inputs(params), asset),
            instruments,
            (data_start, spec.end),
        ),
        equity_interval_ms=spec.equity_interval_ms,
        start=spec.start,
        end=spec.end,
    )


def _instruments(ids: Iterable[str], venue: str) -> list[InstrumentId]:
    instruments = [InstrumentId.from_str(each) for each in ids]
    foreign = [str(each) for each in instruments if each.venue.value != venue]
    if foreign:
        raise InstrumentVenueError(
            f"instruments {', '.join(foreign)} are not on the venue profile's {venue}"
        )
    return instruments


def _seeded(venue: dict[str, Any], seed: int) -> dict[str, Any]:
    """Seed the fill model so random fills are reproducible."""
    if "fill_model" not in venue:
        return venue
    model = venue["fill_model"]
    config = {**model.get("config", {}), "random_seed": seed}
    return {**venue, "fill_model": {**model, "config": config}}


def _data_types(
    inputs: Sequence[BarSpecification], asset: AssetProfile
) -> list[NautilusDataType]:
    """Trades or quotes for the declared bars, plus the asset class's own streams."""
    kinds = {_bar_source(spec) for spec in inputs}
    kinds |= {*asset.carry.data_types, *asset.reference_prices}
    return [
        getattr(NautilusDataType, name) for name in sorted(k.__name__ for k in kinds)
    ]


def _bar_source(spec: BarSpecification) -> type:
    return TradeTick if spec.price_type == PriceType.LAST else QuoteTick


def _data(
    data_types: Iterable[NautilusDataType],
    instruments: Sequence[InstrumentId],
    window: tuple[datetime, datetime],
) -> list[Mapping[str, Any]]:
    start, end = window
    return [
        {
            "data_type": data_type,
            "instrument_ids": list(instruments),
            "start_time": start,
            "end_time": end,
        }
        for data_type in data_types
    ]
