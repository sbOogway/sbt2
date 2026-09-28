from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from nautilus_trader.model import BarType, InstrumentId

type Fetch = Callable[[], Awaitable[bytes]]

# The candles as the origin of a composite bar type, as in
# "BTCUSDT-LINEAR.BYBIT-1-HOUR-LAST-INTERNAL@1-MINUTE-EXTERNAL".
CANDLES = "1-MINUTE-EXTERNAL"


def candle_type(instrument_id: InstrumentId) -> BarType:
    """The bar type of the 1-minute candles a source serves as ``Bar``."""
    return BarType.from_str(f"{instrument_id}-1-MINUTE-LAST-EXTERNAL")


class MissingAtSourceError(LookupError):
    """The source has nothing for this raw file; a 404 means the same for a URL."""


class UnsupportedDataTypeError(LookupError):
    pass


class FundingOffGridError(ValueError):
    """A funding record off its interval's grid, which nautilus would silently skip."""


@dataclass(frozen=True)
class RawFile:
    """One raw file: its path under the raw root, and where it comes from.

    ``origin`` is either a URL, downloaded as is, or a coroutine function returning
    the file's bytes, which raises ``MissingAtSourceError`` when the source has
    nothing for it.
    """

    path: PurePosixPath
    origin: str | Fetch


@dataclass(frozen=True)
class Gap:
    """A day confirmed as unavailable at the source."""

    instrument_id: InstrumentId
    data_type: type
    day: date

    def __str__(self) -> str:
        return f"{self.instrument_id} {self.data_type.__name__} {self.day.isoformat()}"


class Source(Protocol):
    @property
    def data_types(self) -> tuple[type, ...]:
        """Nautilus data types the source serves as one raw file per UTC day."""
        ...

    @property
    def known_gaps(self) -> frozenset[Gap]: ...

    def instrument_id(self, symbol: str) -> InstrumentId: ...

    def symbol(self, instrument_id: InstrumentId) -> str:
        """The inverse of ``instrument_id``."""
        ...

    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        """The raw file holding ``data_type`` for one UTC day."""
        ...

    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        """Today's instrument spec, saved under the date it is taken on."""
        ...

    def parse(self, path: Path, data_type: type, instrument: Any) -> Iterator[Any]:
        """The ``data_type`` records of one raw day file, in time order."""
        ...

    def parse_instrument(self, path: Path) -> Any:
        """The instrument of a snapshot, initialised at the start of its day."""
        ...


def data_types(source: Source, names: tuple[str, ...]) -> tuple[type, ...]:
    """The source's data types called ``names``; all of them when ``names`` is empty."""
    served = {each.__name__: each for each in source.data_types}
    unknown = [each for each in names if each not in served]
    if unknown:
        raise UnsupportedDataTypeError(
            f"the source serves no {', '.join(unknown)}; it serves {', '.join(served)}"
        )
    return tuple(served[each] for each in names) or source.data_types


def is_known_gap(source: Source, symbol: str, data_type: type, day: date) -> bool:
    return Gap(source.instrument_id(symbol), data_type, day) in source.known_gaps
