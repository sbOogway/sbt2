"""A source serving trades as files from a ``FileServer`` and funding from a fake API."""

import asyncio
from collections.abc import Iterator
from datetime import date
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any

from file_server import FileServer
from nautilus_trader.model import FundingRateUpdate, InstrumentId, TradeTick

from sbt2.data.sources import Gap, MissingAtSourceError, RawFile, Source


class FakeApi:
    """Answers each key with its scripted exceptions, in order, then its content."""

    def __init__(self) -> None:
        self.calls: dict[str, int] = {}
        self.in_flight = 0
        self.most_in_flight = 0
        self._content: dict[str, bytes] = {}
        self._errors: dict[str, list[Exception]] = {}

    def serve(self, key: str, content: bytes) -> None:
        self._content[key] = content

    def fail(self, key: str, *errors: Exception) -> None:
        self._errors[key] = list(errors)

    async def fetch(self, key: str) -> bytes:
        self.calls[key] = self.calls.get(key, 0) + 1
        self.in_flight += 1
        self.most_in_flight = max(self.most_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            return self._answer(key)
        finally:
            self.in_flight -= 1

    def _answer(self, key: str) -> bytes:
        errors = self._errors.get(key)
        if errors:
            raise errors.pop(0)
        if key not in self._content:
            raise MissingAtSourceError(f"nothing for {key}")
        return self._content[key]


class FakeSource(Source):
    def __init__(
        self, files: FileServer, api: FakeApi, known_gaps: frozenset[Gap] = frozenset()
    ) -> None:
        super().__init__(known_gaps)
        self._files = files
        self._api = api

    @property
    def data_types(self) -> tuple[type, ...]:
        return (TradeTick, FundingRateUpdate)

    def instrument_id(self, symbol: str) -> InstrumentId:
        return instrument_id(symbol)

    def symbol(self, instrument_id: InstrumentId) -> str:
        return instrument_id.symbol.value

    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        if data_type is TradeTick:
            path = trades_path(symbol, day)
            return RawFile(PurePosixPath("fake", path[1:]), self._files.url(path))
        key = funding_key(symbol, day)
        return RawFile(PurePosixPath("fake", key), partial(self._api.fetch, key))

    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        key = instrument_key(symbol, taken_on)
        return RawFile(PurePosixPath("fake", key), partial(self._api.fetch, key))

    def parse(self, path: Path, data_type: type, instrument: Any) -> Iterator[Any]:
        raise NotImplementedError

    def parse_instrument(self, path: Path) -> Any:
        raise NotImplementedError


def instrument_id(symbol: str) -> InstrumentId:
    return InstrumentId.from_str(f"{symbol}.FAKE")


def trades_path(symbol: str, day: date) -> str:
    return f"/trades/{symbol}/{day.isoformat()}.csv"


def funding_key(symbol: str, day: date) -> str:
    return f"funding/{symbol}/{day.isoformat()}.json"


def instrument_key(symbol: str, day: date) -> str:
    return f"instrument/{symbol}/{day.isoformat()}.json"
