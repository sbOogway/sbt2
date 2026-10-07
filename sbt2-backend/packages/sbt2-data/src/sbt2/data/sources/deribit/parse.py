import json
from collections.abc import Iterator, Mapping, Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from nautilus_trader.model import (
    AggressorSide,
    CryptoOption,
    Currency,
    InstrumentId,
    OptionKind,
    Price,
    Quantity,
    Symbol,
    TradeId,
    TradeTick,
)

VENUE = "DERIBIT"

_NANOS_PER_MILLI = 1_000_000
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


def trades(
    path: Path, instruments: Mapping[InstrumentId, Any]
) -> dict[InstrumentId, list[TradeTick]]:
    """The day file's trades by contract, each list in time order."""
    ticks: dict[InstrumentId, list[TradeTick]] = {each: [] for each in instruments}
    for trade in json.loads(path.read_text()):
        instrument_id = contract_id(trade["instrument_name"])
        ticks[instrument_id].append(_tick(trade, instruments[instrument_id]))
    return ticks


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
