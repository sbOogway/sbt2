import csv
import json
import zipfile
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import override

from sbt2.data.sources.base import Fetch, Gap
from sbt2.data.sources.binance.api import BinanceApi, Endpoints
from sbt2.data.sources.klines import Kline, KlineSource, PerpetualSpec

_PUBLIC = Endpoints()
_PERCENT = Decimal(100)
_NANOS_PER_MILLI = 1_000_000


class BinanceSource(KlineSource):
    """Binance USD-M perpetuals' 1-minute klines, from the daily dumps. The volume
    is in the base coin."""

    name = "binance"
    venue = "BINANCE"
    folder = "binance"
    extension = "zip"
    id_suffix = "-PERP"

    def __init__(
        self, known_gaps: frozenset[Gap] = frozenset(), endpoints: Endpoints = _PUBLIC
    ) -> None:
        super().__init__(known_gaps)
        self._api = BinanceApi(endpoints)

    @override
    def _day_origin(self, symbol: str, day: date) -> Fetch:
        return partial(self._api.klines, symbol, day)

    @override
    async def _snapshot(self, symbol: str) -> bytes:
        return await self._api.instrument_snapshot(symbol)

    @override
    def _klines(self, path: Path) -> Iterator[Kline]:
        with zipfile.ZipFile(path) as dump:
            (member,) = dump.namelist()
            lines = dump.read(member).decode().splitlines()
        # Some dumps start with a header row.
        for row in csv.reader(lines):
            if row[0].isdecimal():
                yield Kline(int(row[0]), *row[1:6])

    @override
    def _spec(self, snapshot: Path, ts_init: int) -> PerpetualSpec:
        spec = json.loads(snapshot.read_text())
        filters = {each["filterType"]: each for each in spec["filters"]}
        return PerpetualSpec(
            base=spec["baseAsset"],
            quote=spec["quoteAsset"],
            settlement=spec["marginAsset"],
            price_increment=filters["PRICE_FILTER"]["tickSize"],
            size_increment=filters["LOT_SIZE"]["stepSize"],
            multiplier="1",
            margin_init=Decimal(spec["requiredMarginPercent"]) / _PERCENT,
            margin_maint=Decimal(spec["maintMarginPercent"]) / _PERCENT,
            ts_event=int(spec["onboardDate"]) * _NANOS_PER_MILLI,
        )
