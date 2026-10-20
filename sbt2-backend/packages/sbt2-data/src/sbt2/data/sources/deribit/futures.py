import re

_SUFFIX = "-FUTURES"
_CURRENCIES = ("BTC", "ETH")
_CONTRACT = re.compile(r"(BTC|ETH)-\d{1,2}[A-Z]{3}\d{2}")

SYMBOLS = tuple(f"{each}{_SUFFIX}" for each in _CURRENCIES)


def currency_of(symbol: str) -> str | None:
    """The currency of a futures symbol, or none when it names no futures."""
    return symbol.removesuffix(_SUFFIX) if symbol in SYMBOLS else None


def symbol_of_contract(name: str) -> str | None:
    """The futures symbol a dated future belongs to, or none when ``name`` is not
    a dated future's name."""
    return f"{name.split('-')[0]}{_SUFFIX}" if _CONTRACT.fullmatch(name) else None
