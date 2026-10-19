from datetime import date, timedelta
from typing import Any, Protocol

from nautilus_trader.adapters.deribit import DeribitHttpClient
from nautilus_trader.model import InstrumentId

from sbt2.data.sources.base import MissingAtSourceError, candle_type
from sbt2.data.sources.klines import utc_day_window
from sbt2.data.sources.nautilus_bars import BarsClient, dump_bars


class DeribitClient(BarsClient, Protocol):
    """What the source uses of ``DeribitHttpClient``."""

    async def request_instrument(self, instrument_id: InstrumentId) -> Any: ...

    def cache_instrument(self, instrument: Any) -> None: ...


class DeribitCandles:
    """The 1-minute bars of a perpetual, through nautilus' HTTP client."""

    def __init__(self, client: DeribitClient | None = None) -> None:
        self._client = client

    async def day(self, symbol: str, day: date) -> bytes:
        """The UTC day's bars, once each. The client needs the instrument cached
        for its bar request, and Deribit includes both ends of the window."""
        client = self._client or DeribitHttpClient()
        instrument_id = InstrumentId.from_str(f"{symbol}.DERIBIT")
        client.cache_instrument(await client.request_instrument(instrument_id))
        first, end = utc_day_window(day)
        bars = await client.request_bars(
            candle_type(instrument_id), first, end - timedelta(milliseconds=1)
        )
        if not bars:
            raise MissingAtSourceError(
                f"deribit has no {symbol} candles on {day.isoformat()}"
            )
        return dump_bars(bars)
