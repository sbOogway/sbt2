from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from nautilus_trader.model import AssetClass, InstrumentClass, InstrumentId

from sbt2.core.assets import AssetProfile, UnknownAssetClassError, asset_profile
from sbt2.core.spec.errors import SpecError
from sbt2.core.spec.resolve.models import built_model, model_tables
from sbt2.data import Source, UnknownSourceError, source_for

_DERIVED = ("name", "source", "asset_class", "instrument_class")


class UnknownVenueError(SpecError, LookupError):
    pass


class InstrumentVenueError(SpecError):
    pass


class InstrumentClassError(SpecError):
    pass


class InvalidExecutionError(SpecError):
    pass


@dataclass(frozen=True)
class Execution:
    """What the run's instruments and the spec's ``[execution]`` table give.

    ``arguments`` are the ``BacktestVenueConfig`` arguments; ``source`` names
    the data source the venue's data comes from."""

    asset: AssetProfile
    source: str
    arguments: dict[str, Any]


def execution(
    instruments: Sequence[InstrumentId], table: Mapping[str, Any]
) -> Execution:
    """The execution of a run on ``instruments`` with the settings ``table``.

    The venue is the one of the instruments and the asset profile follows from
    their class. The arguments start from the asset profile's venue defaults and
    from what the source's data decides; ``table`` overrides them. Model arguments
    stay as ``{kind, config}`` tables until the run config builds them.
    """
    venue = _venue(instruments)
    source = _source(instruments[0])
    asset = _asset(source, instruments)
    _check(table)
    arguments = {"name": venue, **_served(source, asset, instruments[0]), **table}
    return Execution(asset, source.name, _completed(asset, arguments))


def _venue(instruments: Sequence[InstrumentId]) -> str:
    if not instruments:
        raise InstrumentVenueError("the spec names no instruments")
    venues = dict.fromkeys(each.venue.value for each in instruments)
    if len(venues) > 1:
        raise InstrumentVenueError(
            f"the instruments are on {len(venues)} venues, {', '.join(venues)}; "
            "a run trades on one"
        )
    return next(iter(venues))


def _source(instrument: InstrumentId) -> Source:
    try:
        return source_for(instrument)
    except UnknownSourceError as error:
        raise UnknownVenueError(str(error)) from error


def _asset(source: Source, instruments: Sequence[InstrumentId]) -> AssetProfile:
    classes = dict.fromkeys(source.asset_classes(each) for each in instruments)
    if len(classes) > 1:
        names = ", ".join(f"{asset.name}/{kind.name}" for asset, kind in classes)
        raise InstrumentClassError(
            f"the instruments are of {len(classes)} classes, {names}; a run trades one"
        )
    ((asset_class, instrument_class),) = classes
    return _profile(asset_class, instrument_class)


def _profile(
    asset_class: AssetClass, instrument_class: InstrumentClass
) -> AssetProfile:
    try:
        return asset_profile(asset_class, instrument_class)
    except UnknownAssetClassError as error:
        raise InvalidExecutionError(str(error)) from error


def _served(
    source: Source, asset: AssetProfile, instrument: InstrumentId
) -> dict[str, Any]:
    """The settings the source's data decides: a perpetual whose source serves no
    marks takes them from the bars."""
    if asset.instrument_class == InstrumentClass.SWAP and not source.serves_marks(
        instrument
    ):
        return {"marks": "bars"}
    return {}


def _check(table: Mapping[str, Any]) -> None:
    derived = [each for each in _DERIVED if each in table]
    if derived:
        raise InvalidExecutionError(
            f"the execution table sets {', '.join(derived)}, which the instruments give"
        )
    if "fee_model" not in table:
        raise InvalidExecutionError(
            "the spec names no fees: set fee_model in its [execution] table"
        )
    _check_models(table)


def _check_models(arguments: Mapping[str, Any]) -> None:
    for argument, table in model_tables(arguments):
        if "kind" not in table:
            raise InvalidExecutionError(
                f"the execution table names no {argument} kind; "
                "models are not named by import path, name a kind"
            )
        built_model(argument, table)


def _completed(asset: AssetProfile, arguments: Mapping[str, Any]) -> dict[str, Any]:
    quoted = _setting(
        "quotes",
        lambda: asset.quotes.complete({**asset.venue_defaults, **arguments}),
    )
    settled = _setting("delivery_fee", lambda: asset.settlement.complete(quoted))
    return _setting("margin", lambda: asset.margin.complete(settled))


def _setting(setting: str, complete: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    try:
        return complete()
    except ValueError as error:
        raise InvalidExecutionError(
            f"the execution table has invalid {setting}: {error}"
        ) from error
