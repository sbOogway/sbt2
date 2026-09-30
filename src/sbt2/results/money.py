from collections.abc import Iterable

import pandas as pd
from nautilus_trader.model import Money


class CurrencyMismatchError(ValueError):
    pass


def total(frame: pd.DataFrame, column: str, currency: str) -> float:
    """The sum of a column of money amounts, 0 for an empty table."""
    if frame.empty:
        return 0.0
    return sum(amounts(frame[column], currency), 0.0)


def amounts(values: Iterable[str], currency: str) -> list[float]:
    """Money amounts as floats; one in another currency than ``currency`` fails."""
    parsed = [Money.from_str(each) for each in values]
    foreign = {each.currency.code for each in parsed} - {currency}
    if foreign:
        raise _mismatch(foreign, currency)
    return [each.as_double() for each in parsed]


def _mismatch(foreign: set[str], currency: str) -> CurrencyMismatchError:
    return CurrencyMismatchError(
        f"amounts in {', '.join(sorted(foreign))}, not the settlement currency {currency}"
    )
