from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from nautilus_trader.backtest import (
    BacktestDataConfig,
    BacktestEngineConfig,
    BacktestRunConfig,
    BacktestVenueConfig,
)
from nautilus_trader.model import (
    Bar,
    BarSpecification,
    InstrumentId,
    NautilusDataType,
    PriceType,
    QuoteTick,
    TradeTick,
)

from sbt2.assets import AssetProfile
from sbt2.data.sources import CANDLES, candle_type
from sbt2.spec.canonical import canonical_hash, canonical_json
from sbt2.spec.parse import RunSpec
from sbt2.spec.venues import venue_objects, venue_profile
from sbt2.strategy import StrategyRun, import_strategy, resolve_params

_BAR_SOURCES = ("trades", "candles")
_MINUTE = timedelta(minutes=1)


@dataclass(frozen=True)
class ResolvedRunSpec:
    """A run spec with every name replaced by what it stands for.

    ``venue`` and ``data`` are nautilus's own ``BacktestVenueConfig`` and
    ``BacktestDataConfig`` arguments as plain data, without the catalog path.
    ``source`` names where missing data is fetched from; like the catalog path,
    it is not hashed.
    """

    strategy: StrategyRun
    asset: AssetProfile
    source: str
    venue: Mapping[str, Any]
    data: Sequence[Mapping[str, Any]]
    equity_interval_ms: int
    start: datetime
    end: datetime

    @property
    def hash(self) -> str:
        return canonical_hash(self._document())

    def to_json(self) -> str:
        """The canonical JSON the hash is taken of."""
        return canonical_json(self._document())

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
            "start": self.start,
            "end": self.end,
        }


class InstrumentVenueError(ValueError):
    pass


class UnknownBarSourceError(ValueError):
    pass


class CandleBarError(ValueError):
    """A declared bar that 1-minute candles cannot build."""


def resolve(spec: RunSpec, venue_profiles: Path) -> ResolvedRunSpec:
    profile = venue_profile(venue_profiles, spec.venue)
    asset, venue = profile.asset, profile.arguments
    instruments = _instruments(spec.instruments, venue["name"])
    strategy = import_strategy(spec.strategy)
    params = resolve_params(strategy, spec.params)
    data_start = spec.start - strategy.warmup(params)
    return ResolvedRunSpec(
        strategy=StrategyRun(
            spec.strategy,
            instruments,
            asdict(params),
            spec.start,
            CANDLES if spec.bars == "candles" else None,
        ),
        asset=asset,
        source=profile.source,
        venue=_seeded(_venue_arguments(spec, venue), spec.seed),
        data=_data(
            _data_types(_bar_source(spec.bars, strategy.inputs(params)), asset),
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


def _venue_arguments(spec: RunSpec, profile: Mapping[str, Any]) -> dict[str, Any]:
    arguments = {**profile, "starting_balances": [spec.capital]}
    if spec.liquidation is not None:
        arguments["liquidation_enabled"] = spec.liquidation
    return arguments


def _seeded(venue: dict[str, Any], seed: int) -> dict[str, Any]:
    """Seed the fill model so random fills are reproducible."""
    if "fill_model" not in venue:
        return venue
    model = venue["fill_model"]
    config = {**model.get("config", {}), "random_seed": seed}
    return {**venue, "fill_model": {**model, "config": config}}


def _data_types(bar_sources: set[type], asset: AssetProfile) -> list[NautilusDataType]:
    """What the declared bars are built from, plus the asset class's own streams."""
    kinds = bar_sources | {*asset.carry.data_types, *asset.reference_prices}
    return [
        getattr(NautilusDataType, name) for name in sorted(k.__name__ for k in kinds)
    ]


def _bar_source(bars: str, inputs: Sequence[BarSpecification]) -> set[type]:
    if bars == "trades":
        return {_tick_source(spec) for spec in inputs}
    if bars == "candles":
        for spec in inputs:
            _check_candle_built(spec)
        return {Bar}
    raise UnknownBarSourceError(
        f"bars {bars!r} is not one of {', '.join(_BAR_SOURCES)}"
    )


def _tick_source(spec: BarSpecification) -> type:
    return TradeTick if spec.price_type == PriceType.LAST else QuoteTick


def _check_candle_built(spec: BarSpecification) -> None:
    buildable = (
        spec.is_time_aggregated()
        and spec.timedelta % _MINUTE == timedelta(0)
        and spec.price_type == PriceType.LAST
    )
    if not buildable:
        raise CandleBarError(
            f"1-minute candles cannot build {spec} bars; they build time bars "
            "of whole minutes on LAST prices"
        )


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
            **_bar_types(data_type, instruments),
            "start_time": start,
            "end_time": end,
        }
        for data_type in data_types
    ]


def _bar_types(
    data_type: NautilusDataType, instruments: Sequence[InstrumentId]
) -> dict[str, list[str]]:
    if data_type != NautilusDataType.Bar:
        return {}
    return {"bar_types": [str(candle_type(each)) for each in instruments]}
