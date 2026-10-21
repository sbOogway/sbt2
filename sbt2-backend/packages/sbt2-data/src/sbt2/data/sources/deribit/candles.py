from datetime import date, timedelta
from typing import Any, Protocol

from nautilus_trader.adapters.deribit import DeribitHttpClient
from nautilus_trader.model import Bar, InstrumentId

from sbt2.data.sources.base import MissingAtSourceError, candle_type
from sbt2.data.sources.deribit import futures
from sbt2.data.sources.deribit.api import DeribitApi
from sbt2.data.sources.klines import utc_day_window
from sbt2.data.sources.nautilus_bars import BarsClient, dump_bars


class DeribitClient(BarsClient, Protocol):
    """What the source uses of ``DeribitHttpClient``."""

    async def request_instrument(self, instrument_id: InstrumentId) -> Any: ...

    def cache_instrument(self, instrument: Any) -> None: ...


class DeribitCandles:
    """The 1-minute bars of Deribit's perpetuals and dated futures, through
    nautilus' HTTP client. The client needs the instrument cached for its bar
    request, and Deribit includes both ends of the window."""

    def __init__(self, api: DeribitApi, client: DeribitClient | None = None) -> None:
        self._api = api
        self._client = client

    async def day(self, symbol: str, day: date) -> bytes:
        """The UTC day's bars of a perpetual, once each."""
        bars = await self._bars(symbol, day)
        if not bars:
            raise MissingAtSourceError(
                f"deribit has no {symbol} candles on {day.isoformat()}"
            )
        return dump_bars(bars)

    async def futures_day(self, currency: str, day: date) -> bytes:
        """The UTC day's bars of every dated future of the currency alive that day,
        expired ones too, each future's once each."""
        specs = await self._api.future_specs(currency)
        bars = [
            bar
            for spec in specs
            if futures.alive_on(spec, day)
            for bar in await self._bars(spec["instrument_name"], day)
        ]
        if not bars:
            raise MissingAtSourceError(
                f"deribit has no {currency} futures candles on {day.isoformat()}"
            )
        return dump_bars(bars)

    async def _bars(self, name: str, day: date) -> list[Bar]:
        client = self._client or DeribitHttpClient()
        instrument_id = InstrumentId.from_str(f"{name}.DERIBIT")
        client.cache_instrument(await client.request_instrument(instrument_id))
        first, end = utc_day_window(day)
        return await client.request_bars(
            candle_type(instrument_id), first, end - timedelta(milliseconds=1)
        )
