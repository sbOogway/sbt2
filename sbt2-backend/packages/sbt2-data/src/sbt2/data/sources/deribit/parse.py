import json
from collections.abc import Callable, Iterator, Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import (
    AggressorSide,
    CryptoOption,
    Currency,
    GreeksConvention,
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

VENUE = "DERIBIT"

_NANOS_PER_MILLI = 1_000_000
_YEAR_NANOS = 365 * 86_400 * 1_000_000_000
_AGGRESSOR_SIDES = {"buy": AggressorSide.BUY, "sell": AggressorSide.SELL}
_OPTION_KINDS = {"call": OptionKind.CALL, "put": OptionKind.PUT}


def contract_id(name: str) -> InstrumentId:
    return InstrumentId.from_str(f"{name}.{VENUE}")


class Contracts(Mapping[InstrumentId, CryptoOption]):
    """The option contracts of a snapshot, each built when first asked for."""

    def __init__(self, specs: Sequence[Mapping[str, Any]], ts_init: int) -> None:
        self._specs = {contract_id(each["instrument_name"]): each for each in specs}
        self._ts_init = ts_init
        self._built: dict[InstrumentId, CryptoOption] = {}

    def __getitem__(self, instrument_id: InstrumentId) -> CryptoOption:
        if instrument_id not in self._built:
            self._built[instrument_id] = _contract(
                self._specs[instrument_id], self._ts_init
            )
        return self._built[instrument_id]

    def __iter__(self) -> Iterator[InstrumentId]:
        return iter(self._specs)

    def __len__(self) -> int:
        return len(self._specs)


def contracts(path: Path) -> Contracts:
    """The snapshot's contracts, initialised at the start of the day it was taken on."""
    return Contracts(json.loads(path.read_text()), _snapshot_day_nanos(path))


def traded_ids(path: Path) -> tuple[InstrumentId, ...]:
    """The contracts the day file has trades of; none when the file is missing."""
    if not path.is_file():
        return ()
    names = {each["instrument_name"] for each in json.loads(path.read_text())}
    return tuple(contract_id(each) for each in sorted(names))


def day_records(
    path: Path, data_type: type, instruments: Mapping[InstrumentId, Any]
) -> dict[InstrumentId, list[Any]]:
    """The day file's ``data_type`` records by contract, each list in time order."""
    return _by_contract(path, instruments, _BUILDERS[data_type])


def _by_contract(
    path: Path,
    instruments: Mapping[InstrumentId, Any],
    build: Callable[[Mapping[str, Any], CryptoOption], Any],
) -> dict[InstrumentId, list[Any]]:
    records: dict[InstrumentId, list[Any]] = {each: [] for each in instruments}
    for trade in json.loads(path.read_text()):
        instrument_id = contract_id(trade["instrument_name"])
        records[instrument_id].append(build(trade, instruments[instrument_id]))
    return records


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
        contract.id, Price(trade["mark_price"], contract.price_precision), ts, ts
    )


def _option_greeks(trade: Mapping[str, Any], contract: CryptoOption) -> OptionGreeks:
    """The IV and index price of a trade, with the Black-Scholes greeks they give.

    The IV is a fraction (Deribit sends a percentage), the underlying is the
    index price, and the time to expiry counts 365-day years. The rates and the
    cost of carry are 0. The greeks follow nautilus ``black_scholes_greeks`` in
    USD, the quote currency: delta per 1 of the index, gamma per 1 of the index
    squared, vega per IV percentage point and theta per day.
    """
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


_BUILDERS = {
    TradeTick: _tick,
    MarkPriceUpdate: _mark_price,
    OptionGreeks: _option_greeks,
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


def _decimals(number: float) -> int:
    """The decimal places of a number as Deribit writes it."""
    exponent = Decimal(repr(float(number))).normalize().as_tuple().exponent
    return max(0, -int(exponent))


def _snapshot_day_nanos(path: Path) -> int:
    taken_on = date.fromisoformat(path.stem[-len("YYYY-MM-DD") :])
    return pd.Timestamp(taken_on, tz="UTC").value
