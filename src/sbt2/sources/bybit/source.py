from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from functools import partial
from pathlib import PurePosixPath
from typing import Any

from nautilus_trader.model import InstrumentId, TradeTick

from sbt2.sources.base import Gap, RawFile, UnsupportedDataTypeError
from sbt2.sources.bybit.api import BybitApi

_DATA_NAMES: Mapping[str, type] = {"trades": TradeTick}


@dataclass(frozen=True)
class Endpoints:
    api: str = "https://api.bybit.com"
    dumps: str = "https://public.bybit.com"


_PUBLIC = Endpoints()


class BybitSource:
    """Bybit linear perpetuals."""

    def __init__(
        self, known_gaps: frozenset[Gap], endpoints: Endpoints = _PUBLIC
    ) -> None:
        self._known_gaps = known_gaps
        self._endpoints = endpoints
        self._api = BybitApi(endpoints.api)

    @classmethod
    def from_config(cls, table: Mapping[str, Any]) -> BybitSource:
        return cls(frozenset(_gap(each) for each in table.get("known_gaps", ())))

    @property
    def data_types(self) -> tuple[type, ...]:
        return tuple(_DATA_NAMES.values())

    @property
    def known_gaps(self) -> frozenset[Gap]:
        return self._known_gaps

    def instrument_id(self, symbol: str) -> InstrumentId:
        return InstrumentId.from_str(f"{symbol}-LINEAR.BYBIT")

    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        if data_type is not TradeTick:
            raise UnsupportedDataTypeError(
                f"bybit serves no {data_type.__name__} day files"
            )
        name = f"{symbol}{day.isoformat()}.csv.gz"
        return RawFile(
            _symbol_dir(symbol) / "trading" / name,
            f"{self._endpoints.dumps}/trading/{symbol}/{name}",
        )

    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        return RawFile(
            _json_path(symbol, "instrument", taken_on),
            partial(self._api.instrument_snapshot, symbol),
        )


def _json_path(symbol: str, kind: str, day: date) -> PurePosixPath:
    return _symbol_dir(symbol) / kind / f"{symbol}{day.isoformat()}.json"


def _symbol_dir(symbol: str) -> PurePosixPath:
    return PurePosixPath("bybit", "linear", symbol)


def _gap(entry: Mapping[str, Any]) -> Gap:
    return Gap(
        InstrumentId.from_str(f"{entry['symbol']}-LINEAR.BYBIT"),
        _DATA_NAMES[entry["data"]],
        entry["day"],
    )
