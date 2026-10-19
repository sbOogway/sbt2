import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from sbt2.data.sources.base import MissingAtSourceError

_EXCHANGE_INFO = "/fapi/v1/exchangeInfo"
_TIMEOUT = httpx.Timeout(60.0)


class BinanceChecksumError(RuntimeError):
    """A dump does not match the checksum Binance publishes for it."""


@dataclass(frozen=True)
class Endpoints:
    """The hosts of Binance: ``api`` serves the instruments, ``dumps`` the klines."""

    api: str = "https://fapi.binance.com"
    dumps: str = "https://data.binance.vision"


class BinanceApi:
    """Binance's public USD-M futures API and its daily kline dumps."""

    def __init__(self, endpoints: Endpoints) -> None:
        self._endpoints = endpoints

    async def klines(self, symbol: str, day: date) -> bytes:
        """The UTC day's kline dump, a zip, once it matches its checksum."""
        name = f"{symbol}-1m-{day.isoformat()}.zip"
        url = f"{self._endpoints.dumps}/data/futures/um/daily/klines/{symbol}/1m/{name}"
        async with self._http() as http:
            dump = await _get(http, url)
            checksum = await _get(http, f"{url}.CHECKSUM")
        _verify(dump, checksum.decode(), name)
        return dump

    async def instrument_snapshot(self, symbol: str) -> bytes:
        """The perpetual's entry of the exchange info as Binance sends it."""
        async with self._http() as http:
            body = await _get(http, f"{self._endpoints.api}{_EXCHANGE_INFO}")
        spec = _perpetual(json.loads(body)["symbols"], symbol)
        return json.dumps(spec).encode()

    def _http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT)


async def _get(http: httpx.AsyncClient, url: str) -> bytes:
    response = await http.get(url)
    if response.status_code == httpx.codes.NOT_FOUND:
        raise MissingAtSourceError(f"{url}: HTTP 404")
    response.raise_for_status()
    return response.content


def _verify(dump: bytes, checksum: str, name: str) -> None:
    if hashlib.sha256(dump).hexdigest() != checksum.split()[0]:
        raise BinanceChecksumError(f"{name} does not match its checksum")


def _perpetual(symbols: list[dict[str, Any]], symbol: str) -> dict[str, Any]:
    for each in symbols:
        if each["symbol"] == symbol and each["contractType"] == "PERPETUAL":
            return each
    raise MissingAtSourceError(f"binance lists no perpetual {symbol}")
