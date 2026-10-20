"""Stand-ins for the nautilus HTTP clients: they answer with ``Bar`` and
instrument objects, the way the real clients do, without any network.

A day is synthetic: minute ``n`` of 2025-01-01 opens at ``90000 + n``, and trades
``1 + n % 5`` contracts. The clients stamp a bar at its open.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from nautilus_trader.model import (
    Bar,
    BarType,
    CryptoPerpetual,
    InstrumentId,
    Price,
    Quantity,
)

DAY_START_NANOS = 1_735_689_600_000_000_000
MINUTE_NANOS = 60_000_000_000
MINUTES = 1440
OKX_PAGE = 100
HERE = Path(__file__).parent


def load_sample(name: str) -> Any:
    return json.loads((HERE / name).read_text())


def synthetic_day(bar_type: BarType, volume_precision: int) -> list[Bar]:
    """The bars of 2025-01-01, stamped at their open."""
    bars = []
    for n in range(MINUTES):
        base = 90000 + n
        stamp = DAY_START_NANOS + n * MINUTE_NANOS
        bars.append(
            Bar(
                bar_type,
                Price(base, 1),
                Price(base + 5, 1),
                Price(base - 5, 1),
                Price(base + 1, 1),
                Quantity(1 + n % 5, volume_precision),
                stamp,
                stamp,
            )
        )
    return bars


def _nanos(moment: datetime) -> int:
    return (
        (moment - datetime(1970, 1, 1, tzinfo=UTC)) // timedelta(microseconds=1) * 1000
    )


@dataclass
class OkxClientStub:
    """Answers as ``OKXHttpClient`` does: at most 100 bars, the newest of the
    window first excluded from both ends, and bars only for listed instruments."""

    bars: list[Bar]
    instruments: dict[str, Any] = field(default_factory=dict)
    windows: list[tuple[datetime, datetime]] = field(default_factory=list)

    async def request_instrument(self, instrument_id: InstrumentId) -> Any:
        spec = self.instruments.get(instrument_id.symbol.value)
        if spec is None:
            raise ValueError("OKX error 51001: Instrument ID doesn't exist.")
        return CryptoPerpetual.from_dict(spec)

    async def request_bars(
        self, bar_type: BarType, start: datetime, end: datetime
    ) -> list[Bar]:
        self.windows.append((start, end))
        inside = [
            each
            for each in self.bars
            if each.bar_type == bar_type and _nanos(start) < each.ts_event < _nanos(end)
        ]
        return inside[-OKX_PAGE:]


@dataclass
class DeribitClientStub:
    """Answers as ``DeribitHttpClient`` does: the bars of the window with both
    ends included, once the instrument is cached."""

    bars: list[Bar]
    windows: list[tuple[datetime, datetime]] = field(default_factory=list)
    cached: list[Any] = field(default_factory=list)

    async def request_instrument(self, instrument_id: InstrumentId) -> Any:
        return instrument_id

    def cache_instrument(self, instrument: Any) -> None:
        self.cached.append(instrument)

    async def request_bars(
        self, bar_type: BarType, start: datetime, end: datetime
    ) -> list[Bar]:
        self.windows.append((start, end))
        return [
            each
            for each in self.bars
            if each.bar_type == bar_type
            and _nanos(start) <= each.ts_event <= _nanos(end)
        ]
