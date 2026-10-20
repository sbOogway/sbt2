import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

_SUFFIX = "-FUTURES"
_CURRENCIES = ("BTC", "ETH")
_CONTRACT = re.compile(r"(BTC|ETH)-\d{1,2}[A-Z]{3}\d{2}")

SYMBOLS = tuple(f"{each}{_SUFFIX}" for each in _CURRENCIES)


def currency_of(symbol: str) -> str | None:
    """The currency of a futures symbol, or none when it names no futures."""
    return symbol.removesuffix(_SUFFIX) if symbol in SYMBOLS else None


def symbol_of(currency: str) -> str:
    return f"{currency}{_SUFFIX}"


def symbol_of_contract(name: str) -> str | None:
    """The futures symbol a dated future belongs to, or none when ``name`` is not
    a dated future's name."""
    return symbol_of(name.split("-")[0]) if _CONTRACT.fullmatch(name) else None


def alive_on(spec: Mapping[str, Any], day: date) -> bool:
    """Whether the future was listed on or before the UTC day and expires on or
    after it."""
    return _day(spec["creation_timestamp"]) <= day <= _day(spec["expiration_timestamp"])


def _day(milliseconds: int) -> date:
    return datetime.fromtimestamp(milliseconds / 1000, UTC).date()
