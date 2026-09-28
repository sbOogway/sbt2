import json
import re
import urllib.request
from collections.abc import Mapping
from typing import Any

import httpx
from nautilus_trader.adapters.bybit import BybitHttpClient, BybitProductType

from sbt2.sources.base import MissingAtSourceError

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
        has the real rates.
        """
        instrument = await _instrument(self._nautilus(), symbol)
        tier = await self._lowest_risk_tier(symbol)
        return _json(
            {
                **instrument.to_dict(),
                "margin_init": tier["initialMargin"],
                "margin_maint": tier["maintenanceMargin"],
            }
        )

    async def _lowest_risk_tier(self, symbol: str) -> Mapping[str, Any]:
        async with self._http() as http:
            body = await _get(
                http, "/v5/market/risk-limit", {"category": "linear", "symbol": symbol}
            )
        return next(each for each in body["result"]["list"] if each["isLowestRisk"])

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


def _check(code: int, message: str, symbol: str) -> None:
    if code == 0:
        return
    if code == _INVALID_PARAMS and "symbol" in message.lower():
        raise MissingAtSourceError(f"bybit serves no linear symbol {symbol}")
    raise BybitApiError(f"bybit error {code}: {message}")


def _json(content: Any) -> bytes:
    return json.dumps(content, indent=1).encode()
