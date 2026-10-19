import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from sbt2.data.sources.base import MissingAtSourceError
from sbt2.data.sources.klines import Pacer, utc_day_window

_INSTRUMENTS = "/api/v5/public/instruments"
_HISTORY_CANDLES = "/api/v5/market/history-candles"
_PAGE_SIZE = 100
_NO_SUCH_INSTRUMENT = "51001"
_TIMEOUT = httpx.Timeout(60.0)


class OkxApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoints:
    """OKX's API host, and the seconds kept between two calls: the candles
    history allows 20 calls in 2 seconds."""

    api: str = "https://www.okx.com"
    pause: float = 0.12


class OkxApi:
    """OKX's public REST API."""

    def __init__(self, endpoints: Endpoints) -> None:
        self._endpoints = endpoints
        self._pacer = Pacer(endpoints.pause)

    async def candles(self, symbol: str, day: date) -> bytes:
        """The UTC day's 1-minute candles as OKX sends them, each once.

        OKX returns at most 100 candles, newest first, older than ``after``
        and newer than ``before``; the next page continues from the oldest.
        """
        start, end = (int(each.timestamp() * 1000) for each in utc_day_window(day))
        found: dict[str, list[str]] = {}
        after = end
        async with self._http() as http:
            while True:
                params = _candle_params(symbol, start - 1, after)
                page = await self._get(http, _HISTORY_CANDLES, params)
                found.update((each[0], each) for each in page)
                if len(page) < _PAGE_SIZE:
                    break
                after = int(page[-1][0])
        if not found:
            raise MissingAtSourceError(
                f"okx has no {symbol} candles on {day.isoformat()}"
            )
        return json.dumps(
            sorted(found.values(), key=lambda each: int(each[0]))
        ).encode()

    async def instrument_snapshot(self, symbol: str) -> bytes:
        """The swap's spec as OKX sends it."""
        params = {"instType": "SWAP", "instId": symbol}
        async with self._http() as http:
            (spec,) = await self._get(http, _INSTRUMENTS, params)
        return json.dumps(spec).encode()

    async def _get(
        self, http: httpx.AsyncClient, path: str, params: Mapping[str, str]
    ) -> list[Any]:
        await self._pacer.wait()
        response = await http.get(path, params=params)
        response.raise_for_status()
        body = response.json()
        if body["code"] == _NO_SUCH_INSTRUMENT:
            raise MissingAtSourceError(f"okx lists no {params['instId']}")
        if body["code"] != "0":
            raise OkxApiError(f"okx error {body['code']}: {body['msg']}")
        return body["data"]

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._endpoints.api, timeout=_TIMEOUT)


def _candle_params(symbol: str, before: int, after: int) -> dict[str, str]:
    return {
        "instId": symbol,
        "bar": "1m",
        "before": str(before),
        "after": str(after),
        "limit": str(_PAGE_SIZE),
    }
