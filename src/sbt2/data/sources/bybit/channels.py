from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import date
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any

from nautilus_trader.model import Bar, FundingRateUpdate, MarkPriceUpdate, TradeTick

from sbt2.data.sources.base import Fetch, RawFile, UnsupportedDataTypeError
from sbt2.data.sources.bybit import parse
from sbt2.data.sources.bybit.api import BybitApi

type Parser = Callable[[Path, Any], Iterator[Any]]
type ApiFetch = Callable[[BybitApi, str, date], Awaitable[bytes]]


@dataclass(frozen=True)
class Remote:
    """Where Bybit serves raw files: its REST API and its dump site."""

    api: BybitApi
    dumps: str


@dataclass(frozen=True)
class Channel(ABC):
    """One data type as Bybit serves it: one raw file per symbol and UTC day.

    ``name`` is the data type's name in ``config/sources.toml``.
    """

    data_type: type
    name: str
    parser: Parser

    def day_file(self, remote: Remote, symbol: str, day: date) -> RawFile:
        return RawFile(
            symbol_dir(symbol) / self._relative_path(symbol, day),
            self._origin(remote, symbol, day),
        )

    @abstractmethod
    def _relative_path(self, symbol: str, day: date) -> PurePosixPath: ...

    @abstractmethod
    def _origin(self, remote: Remote, symbol: str, day: date) -> str | Fetch: ...


@dataclass(frozen=True)
class _DumpChannel(Channel):
    """Daily gzipped CSV files on Bybit's dump site, downloaded as they are."""

    folder: str

    def _relative_path(self, symbol: str, day: date) -> PurePosixPath:
        return PurePosixPath(self.folder, _dump_name(symbol, day))

    def _origin(self, remote: Remote, symbol: str, day: date) -> str | Fetch:
        return f"{remote.dumps}/{self.folder}/{symbol}/{_dump_name(symbol, day)}"


@dataclass(frozen=True)
class _RestChannel(Channel):
    """A day fetched from Bybit's REST API and saved as JSON."""

    fetch: ApiFetch

    def _relative_path(self, symbol: str, day: date) -> PurePosixPath:
        return json_path(self.name, symbol, day)

    def _origin(self, remote: Remote, symbol: str, day: date) -> str | Fetch:
        return partial(self.fetch, remote.api, symbol, day)


CHANNELS: tuple[Channel, ...] = (
    _DumpChannel(TradeTick, "trades", parse.trades, folder="trading"),
    _RestChannel(FundingRateUpdate, "funding", parse.funding, BybitApi.funding),
    _RestChannel(
        MarkPriceUpdate, "mark_price", parse.mark_prices, BybitApi.mark_prices
    ),
    _RestChannel(Bar, "candles", parse.candles, BybitApi.candles),
)


def channel(data_type: type) -> Channel:
    for each in CHANNELS:
        if each.data_type is data_type:
            return each
    raise UnsupportedDataTypeError(f"bybit serves no {data_type.__name__}")


def named(name: str) -> Channel:
    """The channel called ``name`` in ``config/sources.toml``."""
    return {each.name: each for each in CHANNELS}[name]


def json_path(kind: str, symbol: str, day: date) -> PurePosixPath:
    return PurePosixPath(kind, f"{symbol}{day.isoformat()}.json")


def symbol_dir(symbol: str) -> PurePosixPath:
    return PurePosixPath("bybit", "linear", symbol)


def _dump_name(symbol: str, day: date) -> str:
    return f"{symbol}{day.isoformat()}.csv.gz"
