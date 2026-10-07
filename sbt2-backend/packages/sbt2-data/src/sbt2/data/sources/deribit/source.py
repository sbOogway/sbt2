from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any, override

from nautilus_trader.model import InstrumentId, TradeTick

from sbt2.data.sources.base import (
    Gap,
    RawFile,
    Source,
    UnsupportedDataTypeError,
)
from sbt2.data.sources.deribit import parse
from sbt2.data.sources.deribit.api import DeribitApi


@dataclass(frozen=True)
class Endpoints:
    api: str = "https://history.deribit.com"


_PUBLIC = Endpoints()
_CURRENCIES = ("BTC", "ETH")
_OPTIONS_SUFFIX = "-OPTIONS"
_TRADES = "trades"


class DeribitSource(Source):
    """Deribit options: one raw file per currency and UTC day holds every contract."""

    name = "deribit"

    def __init__(
        self, known_gaps: frozenset[Gap] = frozenset(), endpoints: Endpoints = _PUBLIC
    ) -> None:
        super().__init__(known_gaps)
        self._api = DeribitApi(endpoints.api)

    @property
    def data_types(self) -> tuple[type, ...]:
        return (TradeTick,)

    def instrument_id(self, symbol: str) -> InstrumentId:
        """The id of the currency's options as a whole, which known gaps name."""
        if symbol not in _CURRENCIES:
            raise ValueError(
                f"deribit lists options of {', '.join(_CURRENCIES)}, not {symbol}"
            )
        return InstrumentId.from_str(f"{symbol}{_OPTIONS_SUFFIX}.{parse.VENUE}")

    def symbol(self, instrument_id: InstrumentId) -> str:
        currency = instrument_id.symbol.value.split("-")[0]
        if instrument_id.venue.value != parse.VENUE or currency not in _CURRENCIES:
            raise ValueError(f"{instrument_id} is not a deribit option instrument")
        return currency

    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        if data_type is not TradeTick:
            raise UnsupportedDataTypeError(f"deribit serves no {data_type.__name__}")
        return RawFile(
            _currency_dir(symbol) / _TRADES / _json_name(symbol, day),
            partial(self._api.trades, symbol, day),
        )

    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        return RawFile(
            _currency_dir(symbol) / "instrument" / _json_name(symbol, taken_on),
            partial(self._api.instrument_snapshot, symbol),
        )

    def parse(self, path: Path, data_type: type, instrument: Any) -> Iterator[Any]:
        """The trades of one contract."""
        parsed = self.parse_day(path, data_type, {instrument.id: instrument})
        return iter(parsed[instrument.id])

    def parse_instrument(self, path: Path) -> Any:
        raise NotImplementedError("a deribit snapshot lists many instruments")

    @override
    def parse_instruments(self, path: Path) -> Mapping[InstrumentId, Any]:
        return parse.contracts(path)

    @override
    def day_instrument_ids(
        self, path: Path, instruments: Mapping[InstrumentId, Any], /
    ) -> tuple[InstrumentId, ...]:
        return parse.traded_ids(path)

    @override
    def parse_day(
        self, path: Path, data_type: type, instruments: Mapping[InstrumentId, Any]
    ) -> Mapping[InstrumentId, Sequence[Any]]:
        return parse.trades(path, instruments)

    def _listed_data_type(self, name: str) -> type:
        if name != _TRADES:
            raise UnsupportedDataTypeError(
                f"deribit lists no data type {name}; it lists {_TRADES}"
            )
        return TradeTick


def _currency_dir(currency: str) -> PurePosixPath:
    return PurePosixPath("deribit", "option", currency)


def _json_name(currency: str, day: date) -> str:
    return f"{currency}{day.isoformat()}.json"
