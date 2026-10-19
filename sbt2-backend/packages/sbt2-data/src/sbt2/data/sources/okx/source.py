import json
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import override

from sbt2.data.sources.base import Fetch, Gap
from sbt2.data.sources.klines import Kline, KlineSource, PerpetualSpec
from sbt2.data.sources.okx.api import Endpoints, OkxApi

_PUBLIC = Endpoints()
_NANOS_PER_MILLI = 1_000_000
_MAINT_SHARE = Decimal(2) / Decimal(3)


class OkxSource(KlineSource):
    """OKX linear USDT swaps' 1-minute klines. The volume is in contracts, and
    the instrument's multiplier, OKX's ``ctVal``, is the base coin in one."""

    name = "okx"
    venue = "OKX"
    folder = "okx"

    def __init__(
        self, known_gaps: frozenset[Gap] = frozenset(), endpoints: Endpoints = _PUBLIC
    ) -> None:
        super().__init__(known_gaps)
        self._api = OkxApi(endpoints)

    @override
    def _day_origin(self, symbol: str, day: date) -> Fetch:
        return partial(self._api.candles, symbol, day)

    @override
    async def _snapshot(self, symbol: str) -> bytes:
        return await self._api.instrument_snapshot(symbol)

    @override
    def _klines(self, path: Path) -> Iterator[Kline]:
        for row in json.loads(path.read_text()):
            yield Kline(int(row[0]), *row[1:6])

    @override
    def _spec(self, snapshot: Path, ts_init: int) -> PerpetualSpec:
        spec = json.loads(snapshot.read_text())
        if spec["ctType"] != "linear":
            raise ValueError(f"okx source serves linear swaps, not {spec['instId']}")
        initial = Decimal(1) / Decimal(spec["lever"])
        return PerpetualSpec(
            base=spec["ctValCcy"],
            quote=spec["instFamily"].split("-")[1],
            settlement=spec["settleCcy"],
            price_increment=spec["tickSz"],
            size_increment=spec["lotSz"],
            multiplier=spec["ctVal"],
            margin_init=initial,
            margin_maint=initial * _MAINT_SHARE,
            ts_event=int(spec["listTime"]) * _NANOS_PER_MILLI,
        )
