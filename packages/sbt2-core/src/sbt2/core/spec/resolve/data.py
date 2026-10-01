from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from nautilus_trader.model import BarSpecification, InstrumentId, NautilusDataType

from sbt2.core.assets import AssetProfile
from sbt2.core.data import candle_type
from sbt2.core.spec.bars import BarSource


def data_types(
    bars: BarSource, inputs: Sequence[BarSpecification], asset: AssetProfile
) -> list[NautilusDataType]:
    """What the declared bars are built from, plus the asset class's own streams."""
    kinds = bars.data_types(inputs) | {
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


def _bar_types(
    data_type: NautilusDataType, instruments: Sequence[InstrumentId]
) -> dict[str, list[str]]:
    if data_type != NautilusDataType.Bar:
        return {}
    return {"bar_types": [str(candle_type(each)) for each in instruments]}
