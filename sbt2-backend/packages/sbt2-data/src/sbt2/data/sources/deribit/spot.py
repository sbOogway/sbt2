_QUOTE = "USDC"
_CURRENCIES = ("BTC", "ETH")

SYMBOLS = tuple(f"{each}_{_QUOTE}" for each in _CURRENCIES)


def currency_of(symbol: str) -> str | None:
    """The base currency of a spot pair's symbol, or none when it names no pair."""
    return symbol.removesuffix(f"_{_QUOTE}") if symbol in SYMBOLS else None
