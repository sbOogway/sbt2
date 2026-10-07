import json
from collections.abc import Mapping
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx

from sbt2.data.sources.base import MissingAtSourceError

_TRADES = "/api/v2/public/get_last_trades_by_currency_and_time"
_INSTRUMENTS = "/api/v2/public/get_instruments"
_PAGE_SIZE = 1000
_TIMEOUT = httpx.Timeout(60.0)


class DeribitApiError(RuntimeError):
    pass


class DeribitApi:
    """Deribit's public REST API for options.

    The history host serves every day, the recent ones too; the live host has no
    trades older than about two days.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url = base_url

    async def trades(self, currency: str, day: date) -> bytes:
        """Every option trade of the UTC day as Deribit sends it, oldest first.

        Deribit pages by start time, and a page starts with the trades of its
        first millisecond again; each trade is kept once.
        """
        start, end = _day_window(day)
        found: dict[str, dict[str, Any]] = {}
        async with self._http() as http:
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
        async with self._http() as http:
            specs = [
                spec
                for expired in ("false", "true")
                for spec in await _get(
                    http, _INSTRUMENTS, _instrument_params(currency, expired)
                )
            ]
        return _json(specs)

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self._base_url, timeout=_TIMEOUT)


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


def _day_window(day: date) -> tuple[int, int]:
    """The UTC day as Deribit's inclusive start and end in milliseconds."""
    start = datetime.combine(day, time(), UTC)
    end = start + timedelta(days=1, milliseconds=-1)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _time_order(trade: Mapping[str, Any]) -> tuple[int, int]:
    return trade["timestamp"], trade["trade_seq"]


def _json(content: Any) -> bytes:
    return json.dumps(content, separators=(",", ":")).encode()
