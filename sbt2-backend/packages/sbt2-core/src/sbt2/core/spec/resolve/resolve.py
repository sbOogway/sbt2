import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from nautilus_trader.model import BarSpecification, InstrumentId

from sbt2.core.assets import AssetProfile
from sbt2.core.spec.bars import bar_source
from sbt2.core.spec.errors import SpecError
from sbt2.core.spec.file import RunSpec
from sbt2.core.spec.resolve.canonical import canonical_json
from sbt2.core.spec.resolve.data import data_arguments, data_types
from sbt2.core.spec.resolve.document import lookback
from sbt2.core.spec.resolve.resolved import ResolvedRunSpec, Study
from sbt2.core.spec.resolve.venues import venue_profile
from sbt2.core.spec.risk import risk_limits
from sbt2.core.spec.split import Splitter, from_table
from sbt2.core.strategy import StrategyRun, import_strategy, resolve_params


class InstrumentVenueError(SpecError):
    pass


class UnknownPartError(SpecError):
    pass


class UnsupportedBarsError(SpecError):
    pass


class InvalidChainError(SpecError):
    pass


class InvalidCapitalError(SpecError):
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
    _check_bars(asset, strategy.inputs(params))
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
            short_premium=risk.short_premium,
        ),
        asset=asset,
        source=profile.source,
        venue=_seeded(_venue_arguments(spec, venue), spec.seed),
        data=data_arguments(
            data_types(bars, strategy.inputs(params), profile),
            instruments,
            (start - strategy.warmup(params), end),
        ),
        equity_interval_ms=spec.equity_interval_ms,
        split=split,
        part=part,
        start=start,
        end=end,
        risk=risk.engine,
        chain=_chain(asset, instruments, spec.chain),
        lookback=lookback(strategy, params, risk.short_premium),
        study=_study(spec, split),
    )


def _chain(
    asset: AssetProfile, instruments: Sequence[InstrumentId], table: Mapping[str, Any]
) -> dict[str, Any]:
    """The chain table with its defaults; none unless an instrument names a chain."""
    if not any(asset.chain.names_chain(each) for each in instruments):
        if table:
            raise InvalidChainError("the spec has a chain table but names no chain")
        return {}
    try:
        return asset.chain.complete(table)
    except ValueError as error:
        raise InvalidChainError(str(error)) from error


def _check_bars(asset: AssetProfile, inputs: Sequence[BarSpecification]) -> None:
    refused = asset.quotes.unmakeable(inputs)
    if refused:
        names = ", ".join(str(each) for each in refused)
        raise UnsupportedBarsError(
            f"the venue's data cannot build the bars {names}; "
            "declare MID, BID or ASK bars of the quotes"
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
    arguments = {**profile, "starting_balances": _balances(spec.capital)}
    if spec.liquidation is not None:
        arguments["liquidation_enabled"] = spec.liquidation
    return arguments


def _balances(capital: str | Sequence[str]) -> list[str]:
    balances = [capital] if isinstance(capital, str) else list(capital)
    if not balances:
        raise InvalidCapitalError("the capital names no balance")
    return balances


def _seeded(venue: dict[str, Any], seed: int) -> dict[str, Any]:
    """Seed the fill model so random fills are reproducible."""
    if "fill_model" not in venue:
        return venue
    model = venue["fill_model"]
    config = {**model.get("config", {}), "random_seed": seed}
    return {**venue, "fill_model": {**model, "config": config}}
