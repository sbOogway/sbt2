import json
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from datetime import date
from functools import partial
from pathlib import Path, PurePosixPath
from typing import Any, override

from nautilus_trader.model import (
    IndexPriceUpdate,
    InstrumentId,
    MarkPriceUpdate,
    OptionGreeks,
    TradeTick,
)

from sbt2.data.sources.base import (
    Gap,
    RawFile,
    Source,
    UnsupportedDataTypeError,
)
from sbt2.data.sources.deribit import parse
from sbt2.data.sources.deribit.api import DeribitApi, Endpoints
from sbt2.data.sources.deribit.series import Kind, Series, series_of

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
        self._api = DeribitApi(endpoints)

    @property
    def data_types(self) -> tuple[type, ...]:
        return (TradeTick, MarkPriceUpdate, OptionGreeks, IndexPriceUpdate)

    def instrument_id(self, symbol: str) -> InstrumentId:
        """The id of the currency's options as a whole, which known gaps name, or of
        the index of a series."""
        if series_of(symbol) is not None:
            return parse.series_id(symbol)
        if symbol not in _CURRENCIES:
            raise ValueError(
                f"deribit lists options of {', '.join(_CURRENCIES)}, not {symbol}"
            )
        return InstrumentId.from_str(f"{symbol}{_OPTIONS_SUFFIX}.{parse.VENUE}")

    def symbol(self, instrument_id: InstrumentId) -> str:
        if instrument_id.venue.value == parse.VENUE and series_of(
            instrument_id.symbol.value
        ):
            return instrument_id.symbol.value
        currency = instrument_id.symbol.value.split("-")[0]
        if instrument_id.venue.value != parse.VENUE or currency not in _CURRENCIES:
            raise ValueError(f"{instrument_id} is not a deribit option instrument")
        return currency

    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        series = series_of(symbol)
        if series is not None:
            return self._series_day_file(series, data_type, day)
        if data_type not in self.data_types:
            raise UnsupportedDataTypeError(f"deribit serves no {data_type.__name__}")
        return RawFile(
            _currency_dir(symbol) / _TRADES / _json_name(symbol, day),
            partial(self._api.trades, symbol, day),
        )

    @override
    def is_known_gap(self, symbol: str, data_type: type, day: date) -> bool:
        """A day without trades is a day without any of the data types. A series
        has index prices only, so it is never requested for another data type."""
        if series_of(symbol) is not None:
            return data_type is not IndexPriceUpdate
        return super().is_known_gap(symbol, TradeTick, day)

    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        series = series_of(symbol)
        if series is not None:
            return RawFile(
                _series_dir(series) / "instrument" / _json_name(symbol, taken_on),
                partial(_series_spec, symbol),
            )
        return RawFile(
            _currency_dir(symbol) / "instrument" / _json_name(symbol, taken_on),
            partial(self._api.instrument_snapshot, symbol),
        )

    def parse(self, path: Path, data_type: type, instrument: Any) -> Iterator[Any]:
        """The ``data_type`` records of one contract."""
        parsed = self.parse_day(path, data_type, {instrument.id: instrument})
        return iter(parsed[instrument.id])

    @override
    def parse_instruments(self, path: Path) -> Mapping[InstrumentId, Any]:
        return parse.instruments(path)

    @override
    def day_instrument_ids(
        self, path: Path, data_type: type, instruments: Mapping[InstrumentId, Any]
    ) -> tuple[InstrumentId, ...]:
        return parse.traded_ids(path, data_type)

    @override
    def parse_day(
        self, path: Path, data_type: type, instruments: Mapping[InstrumentId, Any]
    ) -> Mapping[InstrumentId, Sequence[Any]]:
        return parse.day_records(path, data_type, instruments)

    def _series_day_file(self, series: Series, data_type: type, day: date) -> RawFile:
        if data_type is not IndexPriceUpdate:
            raise UnsupportedDataTypeError(
                f"{series.symbol} serves IndexPriceUpdate, not {data_type.__name__}"
            )
        return RawFile(
            _series_dir(series) / _json_name(series.symbol, day),
            partial(self._series_fetcher(series), series.currency, day),
        )

    def _series_fetcher(
        self, series: Series
    ) -> Callable[[str, date], Awaitable[bytes]]:
        return {
            Kind.DVOL: self._api.volatility_index,
            Kind.DELIVERY: self._api.delivery_price,
        }[series.kind]

    def _listed_data_type(self, name: str) -> type:
        if name != _TRADES:
            raise UnsupportedDataTypeError(
                f"deribit lists no data type {name}; it lists {_TRADES}"
            )
        return TradeTick


def _series_dir(series: Series) -> PurePosixPath:
    return PurePosixPath("deribit", series.directory, series.symbol)


async def _series_spec(symbol: str) -> bytes:
    """The snapshot of a series: its index has no spec to fetch."""
    return json.dumps({"index": symbol}).encode()


def _currency_dir(currency: str) -> PurePosixPath:
    return PurePosixPath("deribit", "option", currency)


def _json_name(currency: str, day: date) -> str:
    return f"{currency}{day.isoformat()}.json"
