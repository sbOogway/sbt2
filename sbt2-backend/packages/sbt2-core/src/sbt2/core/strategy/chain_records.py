from array import array
from bisect import bisect_left, bisect_right
from collections.abc import Callable

from nautilus_trader.model import InstrumentId


class _Series:
    """Values in time order, each with the nanosecond time it took effect."""

    def __init__(self) -> None:
        self._times = array("q")
        self._values = array("d")

    def add(self, ts: int, value: float) -> None:
        self._times.append(ts)
        self._values.append(value)

    def at(self, ts: int) -> float | None:
        """The last value at or before ``ts``."""
        found = bisect_right(self._times, ts)
        return self._values[found - 1] if found else None

    def between(self, start: int, end: int) -> list[float]:
        """The values from ``start`` to ``end``, both included."""
        first, last = bisect_left(self._times, start), bisect_right(self._times, end)
        return list(self._values[first:last])


class ChainRecords:
    """What a run heard of the market of a chain, in time order: the IV of each
    contract, the index price and the volatility index. A query gives the records
    as of ``now_ns`` and never one after it."""

    def __init__(self, now_ns: Callable[[], int]) -> None:
        self.now_ns = now_ns
        self._ivs: dict[InstrumentId, _Series] = {}
        self._index = _Series()
        self._volatility = _Series()

    def hear_iv(self, contract: InstrumentId, ts: int, iv: float) -> None:
        self._ivs.setdefault(contract, _Series()).add(ts, iv)

    def hear_index(self, ts: int, price: float) -> None:
        self._index.add(ts, price)

    def hear_volatility(self, ts: int, value: float) -> None:
        self._volatility.add(ts, value)

    def iv(self, contract: InstrumentId) -> float | None:
        series = self._ivs.get(contract)
        return None if series is None else series.at(self.now_ns())

    def index(self) -> float | None:
        return self._index.at(self.now_ns())

    def volatility(self, since: int) -> list[float]:
        """The volatility index values from ``since`` to now."""
        return self._volatility.between(since, self.now_ns())
