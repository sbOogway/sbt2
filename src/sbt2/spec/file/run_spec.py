import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sbt2.spec.bars import bar_source
from sbt2.spec.errors import SpecError
from sbt2.spec.moments import utc
from sbt2.spec.split import Splitter

_INTERVAL = re.compile(r"(\d+)([smhd])")
_UNIT_MS = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}


@dataclass(frozen=True)
class RunSpec:
    """One backtest as written in a spec file.

    ``capital`` is a nautilus money string such as ``"10000 USDT"``.
    ``liquidation`` overrides the venue profile's ``liquidation_enabled``.
    ``bars`` says what the declared bars are aggregated from: ``"trades"`` or
    ``"candles"``.
    ``split`` is a splitter, or a spec file's table of its arguments; ``part``
    names the part of the ``period`` it gives that the run covers.
    ``risk`` holds nautilus's ``RiskEngineConfig`` arguments and the
    ``drawdown_limit`` the strategy base enforces.
    """

    strategy: str
    instruments: list[str]
    period: tuple[datetime, datetime]
    venue: str
    capital: str
    part: str
    split: Splitter | Mapping[str, Any]
    seed: int = 42
    equity_interval: str = "1h"
    liquidation: bool | None = None
    bars: str = "trades"
    params: Mapping[str, Any] = field(default_factory=dict)
    risk: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        start, end = self.period
        object.__setattr__(self, "period", (utc(start), utc(end)))
        bar_source(self.bars)
        _interval_ms(self.equity_interval)

    @property
    def equity_interval_ms(self) -> int:
        return _interval_ms(self.equity_interval)


def _interval_ms(interval: str) -> int:
    match = _INTERVAL.fullmatch(interval)
    if match is None:
        raise SpecError(f"equity interval {interval!r} is not like 30s, 15m, 1h or 1d")
    count, unit = match.groups()
    return int(count) * _UNIT_MS[unit]
