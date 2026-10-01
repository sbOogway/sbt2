import json
import re
import urllib.request
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
from nautilus_trader.adapters.bybit import BybitHttpClient, BybitProductType
from nautilus_trader.model import Bar

from sbt2.core.data.sources.base import MissingAtSourceError, candle_type

_LINEAR = BybitProductType.LINEAR
_INVALID_PARAMS = 10001
_NAUTILUS_ERROR = re.compile(r"Bybit error (\d+): (.*)")


class BybitApiError(RuntimeError):
    pass


class BybitApi:
    """Bybit's public REST API, through nautilus's client where it covers an endpoint."""

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    async def instrument_snapshot(self, symbol: str) -> bytes:
        """Today's spec as nautilus ``to_dict`` JSON, margin from the lowest risk tier.

        Nautilus fills margin with placeholders; the public risk-limit endpoint
        has the real rates. Nautilus drops the funding interval, which Bybit's
        instruments-info has; it is kept in ``info`` as ``fundingInterval``.
        """
        instrument = await _instrument(self._nautilus(), symbol)
        tier = await self._lowest_risk_tier(symbol)
        spec = await self._instrument_info(symbol)
        return _json(
            {
                **instrument.to_dict(),
                "margin_init": tier["initialMargin"],
                "margin_maint": tier["maintenanceMargin"],
                "info": {"fundingInterval": spec["fundingInterval"]},
            }
        )

    async def funding(self, symbol: str, day: date) -> bytes:
        """The UTC day's funding history as nautilus ``to_dict`` JSON."""
        client = self._nautilus()
        instrument = await _instrument(client, symbol)
        client.cache_instrument(instrument)
        start, end = _day_window(day)
        rates = await client.request_funding_rates(_LINEAR, instrument.id, start, end)
        return _json([each.to_dict() for each in rates])

    async def candles(self, symbol: str, day: date) -> bytes:
        """The UTC day's 1-minute candles as nautilus ``to_dict`` JSON, stamped at
        their close.

        A request spans one day: Bybit refuses a month at once (error 10016).
        """
        client = self._nautilus()
        instrument = await _instrument(client, symbol)
        client.cache_instrument(instrument)
        start, end = _day_window(day)
        bars = await client.request_bars(
            _LINEAR, candle_type(instrument.id), start, end
        )
        return _json([Bar.to_dict(each) for each in bars])

    async def mark_prices(self, symbol: str, day: date) -> bytes:
        """The UTC day's 1-minute mark-price klines, each response body as returned."""
        async with self._http() as http:
            pages = [
                await _get(http, "/v5/market/mark-price-kline", params)
                for params in _mark_kline_pages(symbol, day)
            ]
        return _json(pages)

    async def _lowest_risk_tier(self, symbol: str) -> Mapping[str, Any]:
        async with self._http() as http:
            body = await _get(
                http, "/v5/market/risk-limit", {"category": "linear", "symbol": symbol}
            )
        return next(each for each in body["result"]["list"] if each["isLowestRisk"])

    async def _instrument_info(self, symbol: str) -> Mapping[str, Any]:
        async with self._http() as http:
            body = await _get(
                http,
                "/v5/market/instruments-info",
                {"category": "linear", "symbol": symbol, "limit": "1000"},
            )
        (spec,) = body["result"]["list"]
        return spec

    def _nautilus(self) -> BybitHttpClient:
        # Download schedules the retries; nautilus's own would multiply them.
        return BybitHttpClient(
            base_url=self._base_url,
            proxy_url=urllib.request.getproxies().get("https"),
            max_retries=0,
        )

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url)


async def _instrument(client: BybitHttpClient, symbol: str) -> Any:
    try:
        (instrument,) = await client.request_instruments(_LINEAR, symbol)
    except ValueError as error:
        match = _NAUTILUS_ERROR.match(str(error))
        if match:
            _check(int(match[1]), match[2], symbol)
        raise
    return instrument


async def _get(
    http: httpx.AsyncClient, path: str, params: Mapping[str, str]
) -> dict[str, Any]:
    response = await http.get(path, params=params)
    response.raise_for_status()
    body = response.json()
    _check(body["retCode"], body["retMsg"], params["symbol"])
    return body


def _day_window(day: date) -> tuple[datetime, datetime]:
    """The UTC day as Bybit's inclusive, millisecond start and end."""
    start = datetime.combine(day, time(), UTC)
    return start, start + timedelta(days=1, milliseconds=-1)


def _mark_kline_pages(symbol: str, day: date) -> list[dict[str, str]]:
    """Query parameters for a day of 1-minute klines, in two halves of 720.

    Bybit returns at most 1000 klines per request.
    """
    day_start, day_end = (int(each.timestamp() * 1000) for each in _day_window(day))
    half = (day_end + 1 - day_start) // 2
    return [
        {
            "category": "linear",
            "symbol": symbol,
            "interval": "1",
            "start": str(start),
            "end": str(start + half - 1),
            "limit": "1000",
        }
        for start in (day_start, day_start + half)
    ]


def _check(code: int, message: str, symbol: str) -> None:
    if code == 0:
        return
    if code == _INVALID_PARAMS and "symbol" in message.lower():
        raise MissingAtSourceError(f"bybit serves no linear symbol {symbol}")
    raise BybitApiError(f"bybit error {code}: {message}")


def _json(content: Any) -> bytes:
    return json.dumps(content, indent=1).encode()
