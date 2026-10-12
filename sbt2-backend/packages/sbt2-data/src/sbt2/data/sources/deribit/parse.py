import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import (
    AggressorSide,
    CryptoOption,
    Currency,
    GreeksConvention,
    IndexInstrument,
    IndexPriceUpdate,
    InstrumentId,
    MarkPriceUpdate,
    OptionGreeks,
    OptionKind,
    Price,
    Quantity,
    Symbol,
    TradeId,
    TradeTick,
    black_scholes_greeks,
)

from sbt2.data.sources.deribit.series import Kind, Series, series_of

VENUE = "DERIBIT"

_NANOS_PER_MILLI = 1_000_000
_INDEX_PRECISION = 2
# Deribit sends marks with up to 8 decimals, finer than the contract tick.
_MARK_PRECISION = 8
_EXPIRY_TIME = pd.Timedelta(hours=8)
_YEAR_NANOS = 365 * 86_400 * 1_000_000_000
_AGGRESSOR_SIDES = {"buy": AggressorSide.BUY, "sell": AggressorSide.SELL}
_OPTION_KINDS = {"call": OptionKind.CALL, "put": OptionKind.PUT}


def contract_id(name: str) -> InstrumentId:
    return InstrumentId.from_str(f"{name}.{VENUE}")


def series_id(symbol: str) -> InstrumentId:
    return InstrumentId.from_str(f"{symbol}.{VENUE}")


def index_id(currency: str) -> InstrumentId:
    """The id of a currency's USD index, named as Deribit names it."""
    return series_id(f"{currency}_USD")


class Contracts(Mapping[InstrumentId, CryptoOption | IndexInstrument]):
    """The option contracts of a snapshot, each built when first asked for, and the
    USD index of their currency."""

    def __init__(
        self, specs: Sequence[Mapping[str, Any]], currency: str, ts_init: int
    ) -> None:
        self._specs = {contract_id(each["instrument_name"]): each for each in specs}
        self._ts_init = ts_init
        self._index = _index(f"{currency}_USD", ts_init)
        self._built: dict[InstrumentId, CryptoOption] = {}

    def __getitem__(
        self, instrument_id: InstrumentId
    ) -> CryptoOption | IndexInstrument:
        if instrument_id == self._index.id:
            return self._index
        if instrument_id not in self._built:
            self._built[instrument_id] = _contract(
                self._specs[instrument_id], self._ts_init
            )
        return self._built[instrument_id]

    def __iter__(self) -> Iterator[InstrumentId]:
        yield from self._specs
        yield self._index.id

    def __len__(self) -> int:
        return len(self._specs) + 1


def instruments(path: Path) -> Mapping[InstrumentId, Any]:
    """The snapshot's instruments, initialised at the start of the day it was taken
    on: the option contracts and their USD index, or the index of a series."""
    symbol = _snapshot_symbol(path)
    if series_of(symbol) is not None:
        index = _index(symbol, _snapshot_day_nanos(path))
        return {index.id: index}
    return Contracts(json.loads(path.read_text()), symbol, _snapshot_day_nanos(path))


def traded_ids(path: Path, data_type: type) -> tuple[InstrumentId, ...]:
    """The instruments the day file has ``data_type`` records of: the contracts
    traded, or the index of their currency, or the index of the series; none when
    the file is missing."""
    if not path.is_file():
        return ()
    series = series_of(_snapshot_symbol(path))
    if series is not None:
        return (series_id(series.symbol),)
    names = {each["instrument_name"] for each in json.loads(path.read_text())}
    if data_type is IndexPriceUpdate:
        return tuple(index_id(each) for each in sorted({_currency(n) for n in names}))
    return tuple(contract_id(each) for each in sorted(names))


def day_records(
    path: Path, data_type: type, instruments: Mapping[InstrumentId, Any]
) -> Mapping[InstrumentId, list[Any]]:
    """The day file's ``data_type`` records by instrument, each list in time order."""
    series = series_of(_snapshot_symbol(path))
    if series is not None:
        return _series_updates(path, series, instruments)
    return _PARSERS[data_type](path, instruments)


def _by_contract(
    path: Path,
    instruments: Mapping[InstrumentId, Any],
    build: Callable[[Mapping[str, Any], CryptoOption], Any | None],
) -> dict[InstrumentId, list[Any]]:
    records: dict[InstrumentId, list[Any]] = {each: [] for each in instruments}
    for trade in json.loads(path.read_text()):
        instrument_id = contract_id(trade["instrument_name"])
        record = build(trade, instruments[instrument_id])
        if record is not None:
            records[instrument_id].append(record)
    return records


def _index_prices(
    path: Path, instruments: Mapping[InstrumentId, IndexInstrument]
) -> dict[InstrumentId, list[IndexPriceUpdate]]:
    trades = json.loads(path.read_text())
    return {
        each.id: [_index_price(trade, each) for trade in trades]
        for each in instruments.values()
    }


def _series_updates(
    path: Path, series: Series, instruments: Mapping[InstrumentId, IndexInstrument]
) -> dict[InstrumentId, list[IndexPriceUpdate]]:
    ((instrument_id, index),) = instruments.items()
    build = _SERIES_UPDATES[series.kind]
    rows = json.loads(path.read_text())
    return {instrument_id: [build(row, index) for row in rows]}


def _dvol_update(row: Sequence[float], index: IndexInstrument) -> IndexPriceUpdate:
    """The hour's close, at the start of the hour as Deribit stamps the row."""
    ts = int(row[0]) * _NANOS_PER_MILLI
    return IndexPriceUpdate(index.id, Price(row[4], index.price_precision), ts, ts)


def _delivery_update(
    record: Mapping[str, Any], index: IndexInstrument
) -> IndexPriceUpdate:
    """The price of the day, at the expiry of that day."""
    expiry = pd.Timestamp(record["date"], tz="UTC") + _EXPIRY_TIME
    price = Price(record["delivery_price"], index.price_precision)
    return IndexPriceUpdate(index.id, price, expiry.value, expiry.value)


_SERIES_UPDATES: dict[Kind, Callable[[Any, IndexInstrument], Any]] = {
    Kind.DVOL: _dvol_update,
    Kind.DELIVERY: _delivery_update,
}


type _DayParser = Callable[
    [Path, Mapping[InstrumentId, Any]], Mapping[InstrumentId, list[Any]]
]


def _tick(trade: Mapping[str, Any], contract: CryptoOption) -> TradeTick:
    ts = int(trade["timestamp"]) * _NANOS_PER_MILLI
    return TradeTick(
        contract.id,
        Price(trade["price"], contract.price_precision),
        Quantity(trade["amount"], contract.size_precision),
        _AGGRESSOR_SIDES[trade["direction"]],
        TradeId(str(trade["trade_id"])),
        ts,
        ts,
    )


def _mark_price(trade: Mapping[str, Any], contract: CryptoOption) -> MarkPriceUpdate:
    ts = int(trade["timestamp"]) * _NANOS_PER_MILLI
    return MarkPriceUpdate(
        contract.id, Price(trade["mark_price"], _MARK_PRECISION), ts, ts
    )


def _option_greeks(
    trade: Mapping[str, Any], contract: CryptoOption
) -> OptionGreeks | None:
    """The IV and index price of a trade, with the Black-Scholes greeks they give.

    The IV is a fraction (Deribit sends a percentage), the underlying is the
    index price, and the time to expiry counts 365-day years. The rates and the
    cost of carry are 0. The greeks follow nautilus ``black_scholes_greeks`` in
    USD, the quote currency: delta per 1 of the index, gamma per 1 of the index
    squared, vega per IV percentage point and theta per day.

    Deribit sends an IV of 0 for a deep in-the-money trade; its greeks are
    undefined, so it gives none.
    """
    if not trade["iv"]:
        return None
    ts = int(trade["timestamp"]) * _NANOS_PER_MILLI
    iv = trade["iv"] / 100
    index = trade["index_price"]
    years = (contract.expiration_ns - ts) / _YEAR_NANOS
    is_call = contract.option_kind == OptionKind.CALL
    strike = float(contract.strike_price)
    greeks = black_scholes_greeks(index, 0.0, 0.0, iv, is_call, strike, years)
    return OptionGreeks(
        contract.id,
        greeks.delta,
        greeks.gamma,
        greeks.vega,
        greeks.theta,
        mark_iv=iv,
        underlying_price=index,
        ts_event=ts,
        ts_init=ts,
        convention=GreeksConvention.BLACK_SCHOLES,
    )


def _index_price(trade: Mapping[str, Any], index: IndexInstrument) -> IndexPriceUpdate:
    ts = int(trade["timestamp"]) * _NANOS_PER_MILLI
    return IndexPriceUpdate(
        index.id, Price(trade["index_price"], index.price_precision), ts, ts
    )


_PARSERS: dict[type, _DayParser] = {
    TradeTick: partial(_by_contract, build=_tick),
    MarkPriceUpdate: partial(_by_contract, build=_mark_price),
    OptionGreeks: partial(_by_contract, build=_option_greeks),
    IndexPriceUpdate: _index_prices,
}


def _contract(spec: Mapping[str, Any], ts_init: int) -> CryptoOption:
    tick = _decimals(spec["tick_size"])
    lot = _decimals(spec["min_trade_amount"])
    return CryptoOption(
        contract_id(spec["instrument_name"]),
        Symbol(spec["instrument_name"]),
        Currency.from_str(spec["base_currency"]),
        Currency.from_str(spec["quote_currency"]),
        Currency.from_str(spec["settlement_currency"]),
        True,
        _OPTION_KINDS[spec["option_type"]],
        Price(spec["strike"], _decimals(spec["strike"])),
        int(spec["creation_timestamp"]) * _NANOS_PER_MILLI,
        int(spec["expiration_timestamp"]) * _NANOS_PER_MILLI,
        tick,
        lot,
        Price(spec["tick_size"], tick),
        Quantity(spec["min_trade_amount"], lot),
        ts_init,
        ts_init,
        multiplier=Quantity(spec["contract_size"], _decimals(spec["contract_size"])),
    )


def _index(name: str, ts_init: int) -> IndexInstrument:
    return IndexInstrument(
        series_id(name),
        Symbol(name),
        Currency.from_str("USD"),
        _INDEX_PRECISION,
        0,
        Price(10**-_INDEX_PRECISION, _INDEX_PRECISION),
        Quantity.from_int(1),
        ts_init,
        ts_init,
    )


def _snapshot_symbol(path: Path) -> str:
    """The symbol a snapshot or a day file is named after."""
    return path.stem[: -len("YYYY-MM-DD")]


def _currency(name: str) -> str:
    return name.split("-")[0]


def _decimals(number: float) -> int:
    """The decimal places of a number as Deribit writes it."""
    exponent = Decimal(repr(float(number))).normalize().as_tuple().exponent
    return max(0, -int(exponent))


def _snapshot_day_nanos(path: Path) -> int:
    taken_on = date.fromisoformat(path.stem[-len("YYYY-MM-DD") :])
    return pd.Timestamp(taken_on, tz="UTC").value
