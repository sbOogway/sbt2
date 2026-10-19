_SUFFIX = "-PERPETUAL"
_CURRENCIES = ("BTC", "ETH")

SYMBOLS = tuple(f"{each}{_SUFFIX}" for each in _CURRENCIES)


def currency_of(symbol: str) -> str | None:
    """The currency of a perpetual's symbol, or none when it names no perpetual."""
    return symbol.removesuffix(_SUFFIX) if symbol in SYMBOLS else None
