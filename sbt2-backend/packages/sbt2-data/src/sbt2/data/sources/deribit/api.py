import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

from sbt2.data.sources.base import MissingAtSourceError

_TRADES = "/api/v2/public/get_last_trades_by_currency_and_time"
_INSTRUMENTS = "/api/v2/public/get_instruments"
_DVOL = "/api/v2/public/get_volatility_index_data"
_HOURLY = "3600"
_PAGE_SIZE = 1000
_TIMEOUT = httpx.Timeout(60.0)


class DeribitApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class Endpoints:
    """The hosts of Deribit: ``api`` serves the history, ``live`` the series."""

    api: str = "https://history.deribit.com"
    live: str = "https://www.deribit.com"


class DeribitApi:
    """Deribit's public REST API for options.

    The history host serves every day of trades, the recent ones too; the live
    host has no trades older than about two days, but it serves the volatility
    index and the delivery prices, which the history host does not.
    """

    def __init__(self, endpoints: Endpoints) -> None:
        self._endpoints = endpoints

    async def trades(self, currency: str, day: date) -> bytes:
        """Every option trade of the UTC day as Deribit sends it, oldest first.

        Deribit pages by start time, and a page starts with the trades of its
        first millisecond again; each trade is kept once.
        """
        start, end = _day_window(day)
        found: dict[str, dict[str, Any]] = {}
        async with self._http(self._endpoints.api) as http:
            while True:
                page = await _get(http, _TRADES, _trade_params(currency, start, end))
                new = [each for each in page["trades"] if each["trade_id"] not in found]
                found.update((each["trade_id"], each) for each in new)
                if not page["has_more"]:
                    break
                start = _next_start(page, new)
        if not found:
            raise MissingAtSourceError(
                f"deribit has no {currency} option trades on {day.isoformat()}"
            )
        return _json(sorted(found.values(), key=_time_order))

    async def instrument_snapshot(self, currency: str) -> bytes:
        """Every option of the currency as Deribit sends it, expired ones too."""
        async with self._http(self._endpoints.api) as http:
            specs = [
                spec
                for expired in ("false", "true")
                for spec in await _get(
                    http, _INSTRUMENTS, _instrument_params(currency, expired)
                )
            ]
        return _json(specs)

    async def volatility_index(self, currency: str, day: date) -> bytes:
        """The hourly DVOL rows ``[time, open, high, low, close]`` of the UTC day."""
        start, end = _day_window(day)
        async with self._http(self._endpoints.live) as http:
            result = await _get(http, _DVOL, _dvol_params(currency, start, end))
        if result["continuation"] is not None:
            raise DeribitApiError(f"deribit pages the {currency} DVOL of one day")
        if not result["data"]:
            raise MissingAtSourceError(
                f"deribit has no {currency} DVOL on {day.isoformat()}"
            )
        return _json(result["data"])

    def _http(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, timeout=_TIMEOUT)


async def _get(http: httpx.AsyncClient, path: str, params: Mapping[str, str]) -> Any:
    response = await http.get(path, params=params)
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise DeribitApiError(f"deribit error: {body['error']}")
    return body["result"]


def _next_start(page: Mapping[str, Any], new: list[dict[str, Any]]) -> int:
    if not new:
        raise DeribitApiError("deribit has more trades but a page gave none new")
    return int(page["trades"][-1]["timestamp"])


def _trade_params(currency: str, start: int, end: int) -> dict[str, str]:
    return {
        "currency": currency,
        "kind": "option",
        "start_timestamp": str(start),
        "end_timestamp": str(end),
        "count": str(_PAGE_SIZE),
        "sorting": "asc",
    }


def _instrument_params(currency: str, expired: str) -> dict[str, str]:
    return {"currency": currency, "kind": "option", "expired": expired}


def _dvol_params(currency: str, start: int, end: int) -> dict[str, str]:
    return {
        "currency": currency,
        "start_timestamp": str(start),
        "end_timestamp": str(end),
        "resolution": _HOURLY,
    }


def _day_window(day: date) -> tuple[int, int]:
    """The UTC day as Deribit's inclusive start and end in milliseconds."""
    start = datetime.combine(day, time(), UTC)
    end = start + timedelta(days=1, milliseconds=-1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _time_order(trade: Mapping[str, Any]) -> tuple[int, int]:
    return trade["timestamp"], trade["trade_seq"]


def _json(content: Any) -> bytes:
    return json.dumps(content, separators=(",", ":")).encode()
