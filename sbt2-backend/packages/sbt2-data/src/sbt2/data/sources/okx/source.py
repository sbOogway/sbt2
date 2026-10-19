import json
from collections.abc import Iterator
from datetime import date
from functools import partial
from pathlib import Path
from typing import override

from nautilus_trader.model import CryptoPerpetual, InstrumentId

from sbt2.data.sources.base import Fetch, Gap
from sbt2.data.sources.klines import Kline, KlineSource
from sbt2.data.sources.nautilus_bars import read_klines
from sbt2.data.sources.okx.api import OkxApi, OkxClient


class OkxSource(KlineSource):
    """OKX swaps' 1-minute klines, from nautilus' HTTP client. The volume is in
    contracts, and the instrument's multiplier, OKX's ``ctVal``, is the base coin
    in one."""

    name = "okx"
    venue = "OKX"
    folder = "okx"

    def __init__(
        self, known_gaps: frozenset[Gap] = frozenset(), client: OkxClient | None = None
    ) -> None:
        super().__init__(known_gaps)
        self._api = OkxApi(client)

    @override
    def _day_origin(self, symbol: str, day: date) -> Fetch:
        return partial(self._api.candles, symbol, day)

    @override
    async def _snapshot(self, symbol: str) -> bytes:
        return await self._api.instrument_snapshot(symbol)

    @override
    def _klines(self, path: Path) -> Iterator[Kline]:
        return read_klines(path)

    @override
    def _instrument(
        self, snapshot: Path, instrument_id: InstrumentId, ts_init: int
    ) -> CryptoPerpetual:
        spec = json.loads(snapshot.read_text())
        return CryptoPerpetual.from_dict({**spec, "ts_init": ts_init})
