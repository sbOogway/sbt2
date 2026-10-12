from dataclasses import dataclass
from enum import StrEnum

_CURRENCIES = ("BTC", "ETH")


class Kind(StrEnum):
    """The kinds of series; the value ends the series' symbol."""

    DVOL = "DVOL"


@dataclass(frozen=True)
class Series:
    """A volatility or price series of one currency, stored as index prices."""

    symbol: str
    currency: str
    kind: Kind

    @property
    def directory(self) -> str:
        return self.kind.name.lower()


_SERIES = {
    f"{currency}_{kind.value}": Series(f"{currency}_{kind.value}", currency, kind)
    for currency in _CURRENCIES
    for kind in Kind
}


def series_of(symbol: str) -> Series | None:
    return _SERIES.get(symbol)
