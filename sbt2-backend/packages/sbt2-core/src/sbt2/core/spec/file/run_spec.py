import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sbt2.core.spec.bars import bar_source
from sbt2.core.spec.errors import SpecError
from sbt2.core.spec.moments import utc
from sbt2.core.spec.split import Splitter

_INTERVAL = re.compile(r"(\d+)([smhd])")
_UNIT_MS = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}
_SLUG = re.compile(r"[a-z0-9-]+")


class InvalidStudyNameError(SpecError):
    """A study name that is not a slug, which it must be since it names a folder."""


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
    ``study`` names the study the run belongs to, if any.
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
    study: str | None = None

    def __post_init__(self) -> None:
        start, end = self.period
        object.__setattr__(self, "period", (utc(start), utc(end)))
        bar_source(self.bars)
        _interval_ms(self.equity_interval)
        _check_study(self.study)

    @property
    def equity_interval_ms(self) -> int:
        return _interval_ms(self.equity_interval)


def _check_study(study: str | None) -> None:
    if study is not None and _SLUG.fullmatch(study) is None:
        raise InvalidStudyNameError(
            f"study {study!r} is not a slug of lowercase letters, digits and dashes"
        )


def _interval_ms(interval: str) -> int:
    match = _INTERVAL.fullmatch(interval)
    if match is None:
        raise SpecError(f"equity interval {interval!r} is not like 30s, 15m, 1h or 1d")
    count, unit = match.groups()
    return int(count) * _UNIT_MS[unit]
