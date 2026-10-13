from collections.abc import Iterable

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc


class CurrencyMismatchError(ValueError):
    pass


def total(frame: pd.DataFrame, column: str, currency: str) -> float:
    """The sum of a column of money amounts, 0 for an empty table."""
    if frame.empty:
        return 0.0
    return sum(amounts(frame[column], currency), 0.0)


def amounts(values: Iterable[str], currency: str) -> list[float]:
    """Money amounts as floats; one in another currency than ``currency`` fails."""
    found, currencies = split_amounts(values)
    foreign = set(currencies) - {currency}
    if foreign:
        raise mismatch(foreign, currency)
    return found


def split_amounts(values: Iterable[str]) -> tuple[list[float], list[str]]:
    """Money amounts as floats, and the currency of each."""
    parts = _split(pa.array(values, type=pa.string()))
    found = pc.cast(_element(parts, 0), pa.float64()).to_numpy().tolist()
    return found, _element(parts, 1).to_pylist()


def _split(values: pa.Array) -> pa.Array:
    split = pc.SplitPatternOptions(" ", max_splits=1)
    parts = pc.call_function("split_pattern", [values], split)
    lengths = pc.call_function("list_value_length", [parts])
    malformed = pc.fill_null(pc.call_function("not_equal", [lengths, 2]), True)
    if pc.call_function("any", [malformed]).as_py():
        first = values.filter(malformed)[0].as_py()
        raise ValueError(f"{first!r} is not '<amount> <currency>'")
    return parts


def _element(parts: pa.Array, index: int) -> pa.Array:
    return pc.call_function("list_element", [parts, index])


def mismatch(foreign: set[str], currency: str) -> CurrencyMismatchError:
    return CurrencyMismatchError(
        f"amounts in {', '.join(sorted(foreign))}, not the settlement currency {currency}"
    )
