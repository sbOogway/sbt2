from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

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
from sbt2.data.sources import candle_type
from sbt2.spec.errors import SpecError

_MINUTE = timedelta(minutes=1)


class CandleBarError(SpecError):
    """A declared bar that 1-minute candles cannot build."""


def data_types(
    bars: str, inputs: Sequence[BarSpecification], asset: AssetProfile
) -> list[NautilusDataType]:
    """What the declared bars are built from, plus the asset class's own streams."""
    kinds = _BAR_SOURCES[bars](inputs) | {
        *asset.carry.data_types,
        *asset.reference_prices,
    }
    return [
        getattr(NautilusDataType, name) for name in sorted(k.__name__ for k in kinds)
    ]


def data_arguments(
    types: Iterable[NautilusDataType],
    instruments: Sequence[InstrumentId],
    window: tuple[datetime, datetime],
) -> list[Mapping[str, Any]]:
    """``BacktestDataConfig`` arguments reading each type over ``window``."""
    start, end = window
    return [
        {
            "data_type": data_type,
            "instrument_ids": list(instruments),
            **_bar_types(data_type, instruments),
            "start_time": start,
            "end_time": end,
        }
        for data_type in types
    ]


def _from_trades(inputs: Sequence[BarSpecification]) -> set[type]:
    return {
        TradeTick if spec.price_type == PriceType.LAST else QuoteTick for spec in inputs
    }


def _from_candles(inputs: Sequence[BarSpecification]) -> set[type]:
    for spec in inputs:
        _check_candle_built(spec)
    return {Bar}


_BAR_SOURCES: Mapping[str, Callable[[Sequence[BarSpecification]], set[type]]] = {
    "trades": _from_trades,
    "candles": _from_candles,
}


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


def _bar_types(
    data_type: NautilusDataType, instruments: Sequence[InstrumentId]
) -> dict[str, list[str]]:
    if data_type != NautilusDataType.Bar:
        return {}
    return {"bar_types": [str(candle_type(each)) for each in instruments]}
