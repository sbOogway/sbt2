from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from functools import partial
from pathlib import Path
from typing import Any

from nautilus_trader.model import InstrumentId

from sbt2.core.data.sources.base import Gap, RawFile, Source
from sbt2.core.data.sources.bybit import parse
from sbt2.core.data.sources.bybit.api import BybitApi
from sbt2.core.data.sources.bybit.channels import (
    CHANNELS,
    Remote,
    channel,
    json_path,
    named,
    symbol_dir,
)


@dataclass(frozen=True)
class Endpoints:
    api: str = "https://api.bybit.com"
    dumps: str = "https://public.bybit.com"


_PUBLIC = Endpoints()
_LINEAR_SUFFIX = "-LINEAR"


class BybitSource(Source):
    """Bybit linear perpetuals."""

    name = "bybit"

    def __init__(
        self, known_gaps: frozenset[Gap] = frozenset(), endpoints: Endpoints = _PUBLIC
    ) -> None:
        super().__init__(known_gaps)
        self._remote = Remote(BybitApi(endpoints.api), endpoints.dumps)

    @property
    def data_types(self) -> tuple[type, ...]:
        return tuple(each.data_type for each in CHANNELS)

    def instrument_id(self, symbol: str) -> InstrumentId:
        return _instrument_id(symbol)

    def symbol(self, instrument_id: InstrumentId) -> str:
        symbol = instrument_id.symbol.value.removesuffix(_LINEAR_SUFFIX)
        if _instrument_id(symbol) != instrument_id:
            raise ValueError(f"{instrument_id} is not a linear bybit instrument")
        return symbol

    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        return channel(data_type).day_file(self._remote, symbol, day)

    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        return RawFile(
            symbol_dir(symbol) / json_path("instrument", symbol, taken_on),
            partial(self._remote.api.instrument_snapshot, symbol),
        )

    def parse(self, path: Path, data_type: type, instrument: Any) -> Iterator[Any]:
        return channel(data_type).parser(path, instrument)

    def parse_instrument(self, path: Path) -> Any:
        return parse.instrument(path)

    def _config_data_type(self, name: str) -> type:
        return named(name).data_type


def _instrument_id(symbol: str) -> InstrumentId:
    return InstrumentId.from_str(f"{symbol}{_LINEAR_SUFFIX}.BYBIT")
