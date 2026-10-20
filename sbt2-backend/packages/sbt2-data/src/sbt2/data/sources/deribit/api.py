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
_DELIVERY_PRICES = "/api/v2/public/get_delivery_prices"
_FUNDING = "/api/v2/public/get_funding_rate_history"
_CHART = "/api/v2/public/get_tradingview_chart_data"
_HOURLY = "3600"
_DELIVERY_PAGE = 100
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
        return _json(await self._listed(currency, "option"))

    async def future_specs(self, currency: str) -> list[dict[str, Any]]:
        """Every dated future of the currency as Deribit sends it, expired ones too,
        each once."""
        listed = await self._listed(currency, "future")
        found = {each["instrument_name"]: each for each in listed}
        return [each for name, each in found.items() if name != _perpetual(currency)]

    async def future_snapshot(self, currency: str) -> bytes:
        """The dated futures of the currency, as ``future_specs`` gives them."""
        return _json(await self.future_specs(currency))

    async def _live_spec(self, currency: str, kind: str, name: str) -> bytes:
        async with self._http(self._endpoints.live) as http:
            listed = await _get(
                http, _INSTRUMENTS, _instrument_params(currency, "false", kind)
            )
        (spec,) = (each for each in listed if each["instrument_name"] == name)
        return _json(spec)

    async def _listed(self, currency: str, kind: str) -> list[dict[str, Any]]:
        async with self._http(self._endpoints.api) as http:
            return [
                spec
                for expired in ("false", "true")
                for spec in await _get(
                    http, _INSTRUMENTS, _instrument_params(currency, expired, kind)
                )
            ]

    async def perpetual_snapshot(self, currency: str) -> bytes:
        """The currency's inverse perpetual as Deribit sends it."""
        return await self._live_spec(currency, "future", _perpetual(currency))

    async def spot_snapshot(self, currency: str, pair: str) -> bytes:
        """The spot pair as Deribit sends it."""
        return await self._live_spec(currency, "spot", pair)

    async def spot_candles(self, pair: str, day: date) -> bytes:
        """The 1-minute bars of the pair in the UTC day, as Deribit sends them:
        the open times and the prices and volumes in lists."""
        start, end = _day_window(day)
        async with self._http(self._endpoints.api) as http:
            result = await _get(http, _CHART, _chart_params(pair, start, end))
        if not result["ticks"]:
            raise MissingAtSourceError(
                f"deribit has no {pair} candles on {day.isoformat()}"
            )
        return _json(result)

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

    async def delivery_price(self, currency: str, day: date) -> bytes:
        """The day's delivery price record, as a list of one.

        Deribit lists the delivery prices newest first, a page of 100 at a time,
        and the early ones weekly; the page of the day is found by bisection.
        """
        async with self._http(self._endpoints.live) as http:
            record = await _delivery_record(http, f"{currency.lower()}_usd", day)
        if record is None:
            raise MissingAtSourceError(
                f"deribit has no {currency} delivery price on {day.isoformat()}"
            )
        return _json([record])

    async def funding(self, symbol: str, day: date) -> bytes:
        """The hourly funding records of the perpetual stamped in the UTC day.

        Deribit leaves out a record stamped at the start, so the request starts
        1 ms earlier.
        """
        start, end = _day_window(day)
        async with self._http(self._endpoints.live) as http:
            records = await _get(
                http, _FUNDING, _funding_params(symbol, start - 1, end)
            )
        if not records:
            raise MissingAtSourceError(
                f"deribit has no {symbol} funding on {day.isoformat()}"
            )
        return _json(records)

    def _http(self, base_url: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=base_url, timeout=_TIMEOUT)


async def _get(http: httpx.AsyncClient, path: str, params: Mapping[str, str]) -> Any:
    response = await http.get(path, params=params)
    response.raise_for_status()
    body = response.json()
    if "error" in body:
        raise DeribitApiError(f"deribit error: {body['error']}")
    return body["result"]


async def _delivery_record(
    http: httpx.AsyncClient, index: str, day: date
) -> dict[str, Any] | None:
    wanted = day.isoformat()
    first = await _delivery_page(http, index, 0)
    low, high = 0, (first["records_total"] - 1) // _DELIVERY_PAGE
    while low <= high:
        number = (low + high) // 2
        page = first if number == 0 else await _delivery_page(http, index, number)
        records = page["data"]
        if not records:
            return None
        if wanted > records[0]["date"]:
            high = number - 1
        elif wanted < records[-1]["date"]:
            low = number + 1
        else:
            return next((each for each in records if each["date"] == wanted), None)
    return None


async def _delivery_page(http: httpx.AsyncClient, index: str, number: int) -> Any:
    params = {
        "index_name": index,
        "offset": str(number * _DELIVERY_PAGE),
        "count": str(_DELIVERY_PAGE),
    }
    return await _get(http, _DELIVERY_PRICES, params)


def _perpetual(currency: str) -> str:
    return f"{currency}-PERPETUAL"


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


def _instrument_params(
    currency: str, expired: str, kind: str = "option"
) -> dict[str, str]:
    return {"currency": currency, "kind": kind, "expired": expired}


def _dvol_params(currency: str, start: int, end: int) -> dict[str, str]:
    return {
        "currency": currency,
        "start_timestamp": str(start),
        "end_timestamp": str(end),
        "resolution": _HOURLY,
    }


def _chart_params(pair: str, start: int, end: int) -> dict[str, str]:
    return {
        "instrument_name": pair,
        "start_timestamp": str(start),
        "end_timestamp": str(end),
        "resolution": "1",
    }


def _funding_params(symbol: str, start: int, end: int) -> dict[str, str]:
    return {
        "instrument_name": symbol,
        "start_timestamp": str(start),
        "end_timestamp": str(end),
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
