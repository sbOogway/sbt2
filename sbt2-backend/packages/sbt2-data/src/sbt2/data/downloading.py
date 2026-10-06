import asyncio
import logging
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import httpx

from sbt2.data.days import DayRange
from sbt2.data.sources import Fetch, MissingAtSourceError, RawFile, Source
from sbt2.data.tally import Tally

logger = logging.getLogger(__name__)

INSTRUMENT = "instrument"
_TIMEOUT = httpx.Timeout(30.0)
_JITTER = random.SystemRandom()


class Outcome(StrEnum):
    FETCHED = "fetched"
    SKIPPED = "skipped"
    MISSING = "missing"
    FAILED = "failed"


@dataclass(frozen=True)
class DownloadRequest:
    """The range's day files, plus each symbol's instrument snapshot of ``taken_on``."""

    days: DayRange
    taken_on: date = field(default_factory=lambda: datetime.now(UTC).date())


@dataclass(frozen=True)
class Item:
    """One raw file to fetch: ``data`` is a nautilus type name, or ``instrument``."""

    symbol: str
    data: str
    day: date
    raw: RawFile


@dataclass(frozen=True)
class FileResult:
    item: Item
    outcome: Outcome
    reason: str = ""


class Progress(Protocol):
    def planned(self, files: int, /) -> None: ...

    def received(self, size: int, /) -> None: ...

    def finished(self, result: FileResult, /) -> None: ...


class _Silent:
    def planned(self, files: int) -> None:
        pass

    def received(self, size: int) -> None:
        pass

    def finished(self, result: FileResult) -> None:
        pass


@dataclass(frozen=True)
class DownloadOptions:
    """Where raw files go and how they are fetched; ``backoff`` is in seconds."""

    raw: Path
    concurrency: int = 8
    retries: int = 5
    backoff: float = 1.0
    progress: Progress = field(default_factory=_Silent)


class _PermanentError(Exception):
    pass


def download(
    source: Source, request: DownloadRequest, options: DownloadOptions
) -> Tally[FileResult]:
    """Fetch the request's raw files from ``source`` into ``options.raw``.

    Files already there are skipped, days the source lacks are reported as
    missing, and files that still fail after the retries are reported as failed.
    """
    items = list(_plan(source, request))
    options.progress.planned(len(items))
    return Tally(tuple(asyncio.run(_download_all(items, options))))


def _plan(source: Source, request: DownloadRequest) -> Iterator[Item]:
    yield from _snapshots(source, request)
    yield from _day_files(source, request)


def _snapshots(source: Source, request: DownloadRequest) -> Iterator[Item]:
    for symbol in request.days.symbols:
        raw = source.instrument_snapshot(symbol, request.taken_on)
        yield Item(symbol, INSTRUMENT, request.taken_on, raw)


def _day_files(source: Source, request: DownloadRequest) -> Iterator[Item]:
    for symbol, data_type, day in request.days.plan(source):
        raw = source.day_file(symbol, data_type, day)
        yield Item(symbol, data_type.__name__, day, raw)


async def _download_all(
    items: list[Item], options: DownloadOptions
) -> list[FileResult]:
    limit = asyncio.Semaphore(options.concurrency)
    async with httpx.AsyncClient(follow_redirects=True, timeout=_TIMEOUT) as http:
        fetcher = _Fetcher(http, options)

        async def limited(item: Item) -> FileResult:
            async with limit:
                return await fetcher.result(item)

        return await asyncio.gather(*(limited(each) for each in items))


class _Fetcher:
    def __init__(self, http: httpx.AsyncClient, options: DownloadOptions) -> None:
        self._http = http
        self._options = options

    async def result(self, item: Item) -> FileResult:
        target = self._options.raw / item.raw.path
        if target.exists():
            result = FileResult(item, Outcome.SKIPPED)
        else:
            result = await self._retrying(item, target)
        self._options.progress.finished(result)
        return result

    async def _retrying(self, item: Item, target: Path) -> FileResult:
        error: Exception | None = None
        for attempt in range(self._options.retries + 1):
            if error is not None:
                await asyncio.sleep(_backoff(self._options.backoff, attempt))
            try:
                await self._fetch(item.raw.origin, target)
                return FileResult(item, Outcome.FETCHED)
            except MissingAtSourceError as missing:
                return FileResult(item, Outcome.MISSING, str(missing))
            except _PermanentError as permanent:
                return FileResult(item, Outcome.FAILED, str(permanent))
            # A source's fetch raises whatever its client does; all of it is retried.
            except Exception as transient:
                logger.debug("fetching %s failed", item.raw.path, exc_info=True)
                error = transient
        return FileResult(item, Outcome.FAILED, repr(error))

    async def _fetch(self, origin: str | Fetch, target: Path) -> None:
        part = target.with_name(target.name + ".part")
        part.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(origin, str):
            await self._stream(origin, part)
        else:
            await self._call(origin, part)
        part.replace(target)

    async def _stream(self, url: str, part: Path) -> None:
        # h11 raises on a body shorter than its content-length, so a short
        # download fails before the rename. Identity encoding keeps the bytes
        # on disk equal to the file's, and their count equal to content-length.
        headers = {"Accept-Encoding": "identity"}
        async with self._http.stream("GET", url, headers=headers) as response:
            _check_status(response)
            with part.open("wb") as file:
                async for chunk in response.aiter_raw():
                    file.write(chunk)
                    self._options.progress.received(len(chunk))

    async def _call(self, fetch: Fetch, part: Path) -> None:
        content = await fetch()
        part.write_bytes(content)
        self._options.progress.received(len(content))


def _check_status(response: httpx.Response) -> None:
    status = response.status_code
    if status == httpx.codes.NOT_FOUND:
        raise MissingAtSourceError(f"{response.url}: HTTP 404")
    if status == httpx.codes.TOO_MANY_REQUESTS or response.is_server_error:
        response.raise_for_status()
    if not response.is_success:
        raise _PermanentError(f"{response.url}: HTTP {status}")


def _backoff(base: float, attempt: int) -> float:
    """Exponential backoff with full jitter, so retries from many files spread out."""
    return _JITTER.uniform(0, base * 2 ** (attempt - 1))
