import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from sbt2.data.sources.base import MissingAtSourceError
from sbt2.data.sources.klines import Pacer, utc_day_window

_INSTRUMENTS = "/api/v1/instruments"
_PAGE_MINUTES = 288
_TIMEOUT = httpx.Timeout(60.0)


@dataclass(frozen=True)
class Endpoints:
    """The API host of Coinbase International Exchange, and the seconds kept
    between two calls."""

    api: str = "https://api.international.coinbase.com"
    pause: float = 0.12


class CoinbaseIntxApi:
    """Coinbase International Exchange's public REST API."""

    def __init__(self, endpoints: Endpoints) -> None:
        self._endpoints = endpoints
        self._pacer = Pacer(endpoints.pause)

    async def candles(self, symbol: str, day: date) -> bytes:
        """The UTC day's 1-minute candles as Coinbase sends them, each once.

        A request spans at most 300 minutes, both ends included, and Coinbase
        leaves out a minute without a trade.
        """
        first, end = utc_day_window(day)
        found: dict[str, dict[str, str]] = {}
        async with self._http() as http:
            for start in _page_starts(first, end):
                page = await self._candles(http, symbol, start)
                found.update((each["start"], each) for each in page)
        if not found:
            raise MissingAtSourceError(
                f"coinbase_intx has no {symbol} candles on {day.isoformat()}"
            )
        return json.dumps(
            sorted(found.values(), key=lambda each: each["start"])
        ).encode()

    async def instrument_snapshot(self, symbol: str) -> bytes:
        """The perpetual's spec as Coinbase sends it."""
        async with self._http() as http:
            spec = await self._get(http, f"{_INSTRUMENTS}/{symbol}", {})
        return json.dumps(spec).encode()

    async def _candles(
        self, http: httpx.AsyncClient, symbol: str, start: datetime
    ) -> list[dict[str, str]]:
        last = start + timedelta(minutes=_PAGE_MINUTES - 1)
        params = {
            "granularity": "ONE_MINUTE",
            "start": _iso(start),
            "end": _iso(last),
        }
        body = await self._get(http, f"{_INSTRUMENTS}/{symbol}/candles", params)
        return body.get("aggregations", [])

    async def _get(
        self, http: httpx.AsyncClient, path: str, params: dict[str, str]
    ) -> Any:
        await self._pacer.wait()
        response = await http.get(path, params=params)
        if response.status_code == httpx.codes.NOT_FOUND or _unknown(response):
            raise MissingAtSourceError(f"{response.url}: no such instrument")
        response.raise_for_status()
        return response.json()

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._endpoints.api, timeout=_TIMEOUT)


def _page_starts(first: datetime, end: datetime) -> list[datetime]:
    page = timedelta(minutes=_PAGE_MINUTES)
    return [first + each * page for each in range((end - first) // page)]


def _unknown(response: httpx.Response) -> bool:
    return (
        response.status_code == httpx.codes.BAD_REQUEST
        and response.json().get("title") == "instrument not found"
    )


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")
