"""The raw file of the sources that get their bars from a nautilus HTTP client:
the bars as the client returns them, as JSON."""

import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol

from nautilus_trader.model import Bar, BarType

from sbt2.data.sources.klines import Kline

_NANOS_PER_MILLI = 1_000_000
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class BarsClient(Protocol):
    """What the sources use of a nautilus HTTP client to get bars."""

    async def request_bars(
        self, bar_type: BarType, start: datetime, end: datetime
    ) -> list[Bar]: ...


def dump_bars(bars: Iterable[Bar]) -> bytes:
    """The bars as nautilus gives them, which keeps every field."""
    return json.dumps([each.to_dict() for each in bars]).encode()


def read_bars(path: Path) -> list[Bar]:
    """The bars of a raw file."""
    return [Bar.from_dict(each) for each in json.loads(path.read_text())]


def read_klines(path: Path) -> Iterator[Kline]:
    """The bars of a raw file as klines, which the nautilus clients stamp at the
    open, in time order."""
    return klines_of(read_bars(path))


def klines_of(bars: Iterable[Bar]) -> Iterator[Kline]:
    """The bars as klines, in time order."""
    for bar in sorted(bars, key=lambda each: each.ts_event):
        yield Kline(
            bar.ts_event // _NANOS_PER_MILLI,
            str(bar.open),
            str(bar.high),
            str(bar.low),
            str(bar.close),
            str(bar.volume),
        )


def utc_time(nanos: int) -> datetime:
    """The UTC time of a nanosecond stamp, to the microsecond."""
    return _EPOCH + timedelta(microseconds=nanos // 1000)
