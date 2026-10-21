from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from nautilus_trader.model import (
    AssetClass,
    InstrumentClass,
    InstrumentId,
    NautilusDataType,
)

from sbt2.core.assets import AssetProfile, asset_profile
from sbt2.core.spec.errors import SpecError
from sbt2.core.spec.resolve.models import model_tables
from sbt2.core.spec.risk import risk_limits
from sbt2.core.spec.split import Splitter, from_table
from sbt2.core.strategy import (
    IV_LOOKBACK,
    ShortPremiumRules,
    Strategy,
    StrategyRun,
    import_strategy,
    resolve_params,
)
from sbt2.data import CANDLES

type Document = Mapping[str, Any]

_TICKS = frozenset({NautilusDataType.TradeTick, NautilusDataType.QuoteTick})


class OutdatedRunError(SpecError):
    pass


def spec_fields(
    document: Document, strategy_source: Path | None = None
) -> dict[str, Any]:
    """The ``ResolvedRunSpec`` fields its hashed document holds, typed back; the
    strategy's module is read from ``strategy_source`` when given."""
    asset = _asset(document)
    data = [_data_arguments(each) for each in document["data"]]
    risk = risk_limits(document.get("risk", {}))
    strategy = import_strategy(document["strategy"]["path"], strategy_source)
    return {
        "strategy": _strategy(
            document["strategy"],
            strategy,
            _Streaming(_aggregated_from(data), risk.drawdown_limit, risk.short_premium),
        ),
        "asset": asset,
        "venue": _venue(document["venue"], asset),
        "data": data,
        "equity_interval_ms": document["equity_interval_ms"],
        "split": _split(document["split"]),
        "part": document["part"],
        "start": datetime.fromisoformat(document["start"]),
        "end": datetime.fromisoformat(document["end"]),
        "risk": risk.engine,
        "chain": document.get("chain", {}),
        "feeds": tuple(_instrument_ids(document.get("feeds", []))),
        "lookback": lookback(
            strategy,
            resolve_params(strategy, document["strategy"]["params"]),
            risk.short_premium,
        ),
    }


def lookback(
    strategy: type[Strategy[Any]], params: Any, rules: ShortPremiumRules | None
) -> timedelta:
    """How far before the data the volatility index is loaded: the strategy's
    look-back, and at least ``IV_LOOKBACK`` when the short premium rules read the
    IV rank."""
    wanted = strategy.iv_lookback(params)
    return wanted if rules is None else max(wanted, IV_LOOKBACK)


def _asset(document: Document) -> AssetProfile:
    return asset_profile(
        AssetClass.from_str(document["asset_class"]),
        InstrumentClass.from_str(document["instrument_class"]),
    )


@dataclass(frozen=True)
class _Streaming:
    aggregated_from: str | None
    drawdown_limit: Decimal | None
    short_premium: ShortPremiumRules | None


def _strategy(
    document: Document, strategy: type[Strategy[Any]], streaming: _Streaming
) -> StrategyRun:
    params = resolve_params(strategy, document["params"])
    return StrategyRun(
        document["path"],
        _instrument_ids(document["instruments"]),
        asdict(params),
        datetime.fromisoformat(document["trade_start"]),
        streaming.aggregated_from,
        streaming.drawdown_limit,
        short_premium=streaming.short_premium,
    )


def _aggregated_from(data: list[dict[str, Any]]) -> str | None:
    """A run on candles streams bars and no ticks; the others build their bars
    from ticks, and may stream bars to make marks from."""
    streamed = {each["data_type"] for each in data}
    if NautilusDataType.Bar not in streamed or streamed & _TICKS:
        return None
    return CANDLES


def _venue(document: Document, asset: AssetProfile) -> dict[str, Any]:
    """The venue arguments, with the asset defaults' objects in place of their
    names."""
    _check_kinds(document)
    return {
        key: _default_or(value, asset.venue_defaults.get(key))
        for key, value in document.items()
    }


def _check_kinds(venue: Document) -> None:
    for argument, table in model_tables(venue):
        if "kind" not in table:
            raise OutdatedRunError(
                f"the run predates model kinds: its {argument} is named by import path"
            )


def _default_or(value: Any, default: Any) -> Any:
    return default if getattr(default, "name", None) == value else value


def _data_arguments(document: Document) -> dict[str, Any]:
    return {
        **document,
        "data_type": getattr(NautilusDataType, document["data_type"]),
        "instrument_ids": _instrument_ids(document["instrument_ids"]),
        "start_time": datetime.fromisoformat(document["start_time"]),
        "end_time": datetime.fromisoformat(document["end_time"]),
    }


def _split(document: Document) -> Splitter:
    return from_table({key: value for key, value in document.items() if key != "kind"})


def _instrument_ids(ids: list[str]) -> list[InstrumentId]:
    return [InstrumentId.from_str(each) for each in ids]
