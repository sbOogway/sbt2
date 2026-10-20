import json
from datetime import date, timedelta
from typing import Any, Protocol

from nautilus_trader.adapters.okx import OKXHttpClient
from nautilus_trader.model import Bar, InstrumentId

from sbt2.data.sources.base import MissingAtSourceError, candle_type
from sbt2.data.sources.klines import utc_day_window
from sbt2.data.sources.nautilus_bars import BarsClient, dump_bars, utc_time

_PAGE_SIZE = 100
_NO_SUCH_INSTRUMENT = "51001"
# The client asks for keys although the public calls do not use them.
_KEY = "public"


class OkxClient(BarsClient, Protocol):
    """What the source uses of ``OKXHttpClient``."""

    async def request_instrument(self, instrument_id: InstrumentId) -> Any: ...


class OkxApi:
    """OKX's public API, through nautilus' HTTP client."""

    def __init__(self, client: OkxClient | None = None) -> None:
        self._client = client

    async def candles(self, symbol: str, day: date) -> bytes:
        """The UTC day's 1-minute bars, each once.

        The client returns the newest 100 bars of a window, so the window's end
        moves back to the oldest bar until a page is not full. OKX leaves out
        the bar at the window's start, so the window starts 1 ms early.
        """
        client = self._http()
        instrument_id = InstrumentId.from_str(f"{symbol}.OKX")
        await _instrument(client, instrument_id)
        first, end = utc_day_window(day)
        start = first - timedelta(milliseconds=1)
        found: dict[int, Bar] = {}
        while True:
            page = await client.request_bars(
                candle_type(instrument_id), start=start, end=end
            )
            found.update((each.ts_event, each) for each in page)
            if len(page) < _PAGE_SIZE:
                break
            end = utc_time(min(each.ts_event for each in page))
        if not found:
            raise MissingAtSourceError(
                f"okx has no {symbol} candles on {day.isoformat()}"
            )
        return dump_bars(found.values())

    async def instrument_snapshot(self, symbol: str) -> bytes:
        """The swap as nautilus builds it from OKX's spec."""
        instrument = await _instrument(
            self._http(), InstrumentId.from_str(f"{symbol}.OKX")
        )
        return json.dumps(instrument.to_dict()).encode()

    def _http(self) -> OkxClient:
        return self._client or OKXHttpClient(_KEY, _KEY, _KEY)


async def _instrument(client: OkxClient, instrument_id: InstrumentId) -> Any:
    """The swap, which the real client also caches for its bar requests."""
    try:
        return await client.request_instrument(instrument_id)
    except ValueError as error:
        if _NO_SUCH_INSTRUMENT in str(error):
            raise MissingAtSourceError(
                f"okx lists no {instrument_id.symbol}"
            ) from error
        raise
