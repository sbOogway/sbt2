import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from nautilus_trader.model import InstrumentId

from sbt2.core.spec.bars import bar_source
from sbt2.core.spec.errors import SpecError
from sbt2.core.spec.file import RunSpec
from sbt2.core.spec.resolve.canonical import canonical_json
from sbt2.core.spec.resolve.data import data_arguments, data_types
from sbt2.core.spec.resolve.resolved import ResolvedRunSpec, Study
from sbt2.core.spec.resolve.venues import venue_profile
from sbt2.core.spec.risk import risk_limits
from sbt2.core.spec.split import Splitter, from_table
from sbt2.core.strategy import StrategyRun, import_strategy, resolve_params


class InstrumentVenueError(SpecError):
    pass


class UnknownPartError(SpecError):
    pass


_UNFIXED = frozenset({"params", "part", "study"})


def resolve(spec: RunSpec, venue_profiles: Path) -> ResolvedRunSpec:
    profile = venue_profile(venue_profiles, spec.venue)
    asset, venue = profile.asset, profile.arguments
    instruments = _instruments(spec.instruments, venue["name"])
    strategy = import_strategy(spec.strategy)
    params = resolve_params(strategy, spec.params)
    split, part = _splitter(spec.split), spec.part
    bars = bar_source(spec.bars)
    start, end = _part_dates(split.parts(spec.period), part)
    risk = risk_limits(spec.risk)
    return ResolvedRunSpec(
        strategy=StrategyRun(
            spec.strategy,
            instruments,
            asdict(params),
            start,
            bars.aggregated_from,
            risk.drawdown_limit,
        ),
        asset=asset,
        source=profile.source,
        venue=_seeded(_venue_arguments(spec, venue), spec.seed),
        data=data_arguments(
            data_types(bars, strategy.inputs(params), asset),
            instruments,
            (start - strategy.warmup(params), end),
        ),
        equity_interval_ms=spec.equity_interval_ms,
        split=split,
        part=part,
        start=start,
        end=end,
        risk=risk.engine,
        study=_study(spec, split),
    )


def _study(spec: RunSpec, split: Splitter) -> Study | None:
    if spec.study is None:
        return None
    context = {
        each.name: getattr(spec, each.name)
        for each in fields(spec)
        if each.name not in _UNFIXED
    }
    context["split"] = split.document()
    return Study(spec.study, json.loads(canonical_json(context)))


def _splitter(split: Splitter | Mapping[str, Any]) -> Splitter:
    """A spec file's split table as the splitter it names."""
    if isinstance(split, Splitter):
        return split
    return from_table(split)


def _part_dates(
    parts: Mapping[str, tuple[datetime, datetime]], part: str
) -> tuple[datetime, datetime]:
    if part not in parts:
        raise UnknownPartError(f"part {part!r} is not one of {', '.join(parts)}")
    return parts[part]


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
