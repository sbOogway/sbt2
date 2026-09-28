import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

_INTERVAL = re.compile(r"(\d+)([smhd])")
_UNIT_MS = {"s": 1_000, "m": 60_000, "h": 3_600_000, "d": 86_400_000}


class UnknownSpecKeyError(ValueError):
    pass


@dataclass(frozen=True)
class RunSpec:
    """One backtest as written in a spec file.

    ``capital`` is a nautilus money string such as ``"10000 USDT"``.
    ``liquidation`` overrides the venue profile's ``liquidation_enabled``.
    """

    strategy: str
    instruments: list[str]
    start: datetime
    end: datetime
    venue: str
    capital: str
    seed: int = 42
    equity_interval: str = "1h"
    liquidation: bool | None = None
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", utc(self.start))
        object.__setattr__(self, "end", utc(self.end))

    @property
    def equity_interval_ms(self) -> int:
        match = _INTERVAL.fullmatch(self.equity_interval)
        if match is None:
            raise ValueError(
                f"equity interval {self.equity_interval!r} is not like 30s, 15m, 1h or 1d"
            )
        count, unit = match.groups()
        return int(count) * _UNIT_MS[unit]


def read_spec(path: Path, overrides: Mapping[str, Any]) -> RunSpec:
    with path.open("rb") as file:
        table = tomllib.load(file)
    values = {**table, **overrides}
    _reject_unknown(path, values)
    return RunSpec(**values)


def _reject_unknown(path: Path, values: Mapping[str, Any]) -> None:
    valid = {each.name for each in fields(RunSpec)}
    unknown = sorted(set(values) - valid)
    if unknown:
        raise UnknownSpecKeyError(
            f"unknown keys {', '.join(unknown)} in {path}; "
            f"valid: {', '.join(sorted(valid))}"
        )


def utc(moment: date | datetime | str) -> datetime:
    """A TOML date or datetime as an aware UTC datetime; naive values are UTC."""
    if isinstance(moment, str):
        moment = datetime.fromisoformat(moment)
    if not isinstance(moment, datetime):
        moment = datetime.combine(moment, time())
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)
