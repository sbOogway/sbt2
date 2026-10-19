import json
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import override

from sbt2.data.sources.base import Fetch, Gap
from sbt2.data.sources.coinbase_intx.api import CoinbaseIntxApi, Endpoints
from sbt2.data.sources.klines import Kline, KlineSource, PerpetualSpec

_PUBLIC = Endpoints()
_MAINT_SHARE = Decimal(1) / Decimal(2)


class CoinbaseIntxSource(KlineSource):
    """Coinbase International Exchange perpetuals' 1-minute klines. The volume is
    in the base coin, and the instrument's multiplier, Coinbase's
    ``base_asset_multiplier``, is the base coin in one volume unit."""

    name = "coinbase_intx"
    venue = "COINBASE_INTX"
    folder = "coinbase_intx"

    def __init__(
        self, known_gaps: frozenset[Gap] = frozenset(), endpoints: Endpoints = _PUBLIC
    ) -> None:
        super().__init__(known_gaps)
        self._api = CoinbaseIntxApi(endpoints)

    @override
    def _day_origin(self, symbol: str, day: date) -> Fetch:
        return partial(self._api.candles, symbol, day)

    @override
    async def _snapshot(self, symbol: str) -> bytes:
        return await self._api.instrument_snapshot(symbol)

    @override
    def _klines(self, path: Path) -> Iterator[Kline]:
        for each in json.loads(path.read_text()):
            opened = datetime.fromisoformat(each["start"])
            yield Kline(
                int(opened.timestamp()) * 1000,
                each["open"],
                each["high"],
                each["low"],
                each["close"],
                each["volume"],
            )

    @override
    def _spec(self, snapshot: Path, ts_init: int) -> PerpetualSpec:
        """The margin is a placeholder: the initial one is Coinbase's base
        requirement and the maintenance one half of it."""
        spec = json.loads(snapshot.read_text())
        initial = Decimal(str(spec["base_imf"]))
        return PerpetualSpec(
            base=spec["base_asset_name"],
            quote=spec["quote_asset_name"],
            settlement=spec["quote_asset_name"],
            price_increment=spec["quote_increment"],
            size_increment=spec["base_increment"],
            multiplier=spec["base_asset_multiplier"],
            margin_init=initial,
            margin_maint=initial * _MAINT_SHARE,
            ts_event=ts_init,
        )
