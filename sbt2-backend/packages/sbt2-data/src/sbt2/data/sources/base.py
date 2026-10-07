from abc import ABC, abstractmethod
from collections.abc import (
    Awaitable,
    Callable,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
)
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar, Self

import nautilus_trader.model
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

    @classmethod
    def from_str(cls, text: str) -> Gap:
        """The gap ``str`` gave, of one of nautilus's model data types."""
        instrument_id, data_type, day = text.split(" ")
        return cls(
            InstrumentId.from_str(instrument_id),
            getattr(nautilus_trader.model, data_type),
            date.fromisoformat(day),
        )


class Source(ABC):
    """Where raw market data comes from, one raw file per symbol and UTC day.

    ``name`` is the source's list in the data root's ``known_gaps.toml``.
    ``listing`` builds the source from that list, so a subclass must be
    constructible from its known gaps alone.
    """

    name: ClassVar[str]

    def __init__(self, known_gaps: frozenset[Gap] = frozenset()) -> None:
        self._known_gaps = known_gaps

    @classmethod
    def listing(cls, entries: Iterable[Mapping[str, Any]]) -> Self:
        """The source with the known gaps ``entries`` list."""
        unconfigured = cls()
        return cls(frozenset(unconfigured._gap(each) for each in entries))

    @property
    def known_gaps(self) -> frozenset[Gap]:
        """Days confirmed as unavailable at the source, never requested."""
        return self._known_gaps

    def served(self, names: tuple[str, ...]) -> tuple[type, ...]:
        """The data types called ``names``; all of them when ``names`` is empty."""
        served = {each.__name__: each for each in self.data_types}
        unknown = [each for each in names if each not in served]
        if unknown:
            raise UnsupportedDataTypeError(
                f"the source serves no {', '.join(unknown)}; "
                f"it serves {', '.join(served)}"
            )
        return tuple(served[each] for each in names) or self.data_types

    def is_known_gap(self, symbol: str, data_type: type, day: date) -> bool:
        return Gap(self.instrument_id(symbol), data_type, day) in self.known_gaps

    def _gap(self, entry: Mapping[str, Any]) -> Gap:
        data_type = self._listed_data_type(entry["data"])
        return Gap(self.instrument_id(entry["symbol"]), data_type, entry["day"])

    def _listed_data_type(self, name: str) -> type:
        """The data type called ``name`` in the known gaps file, by default by
        its nautilus name."""
        (data_type,) = self.served((name,))
        return data_type

    @property
    @abstractmethod
    def data_types(self) -> tuple[type, ...]:
        """Nautilus data types the source serves as one raw file per UTC day."""

    @abstractmethod
    def instrument_id(self, symbol: str) -> InstrumentId: ...

    @abstractmethod
    def symbol(self, instrument_id: InstrumentId) -> str:
        """The inverse of ``instrument_id``."""

    @abstractmethod
    def day_file(self, symbol: str, data_type: type, day: date) -> RawFile:
        """The raw file holding ``data_type`` for one UTC day."""

    @abstractmethod
    def instrument_snapshot(self, symbol: str, taken_on: date) -> RawFile:
        """Today's instrument spec, saved under the date it is taken on."""

    @abstractmethod
    def parse(self, path: Path, data_type: type, instrument: Any) -> Iterator[Any]:
        """The ``data_type`` records of one raw day file, in time order."""

    @abstractmethod
    def parse_instrument(self, path: Path) -> Any:
        """The instrument of a snapshot, initialised at the start of its day."""

    def parse_instruments(self, path: Path) -> Mapping[InstrumentId, Any]:
        """The instruments of a snapshot by id; the lookup may build them on demand.

        A source whose raw file holds many instruments overrides this, ``parse_day``
        and ``day_instrument_ids``; the default is the snapshot's one instrument.
        """
        instrument = self.parse_instrument(path)
        return {instrument.id: instrument}

    def day_instrument_ids(
        self, _path: Path, instruments: Mapping[InstrumentId, Any]
    ) -> tuple[InstrumentId, ...]:
        """The ids of the ``instruments`` the raw day file holds records of; none
        when the file is missing."""
        return tuple(instruments)

    def parse_day(
        self, path: Path, data_type: type, instruments: Mapping[InstrumentId, Any]
    ) -> Mapping[InstrumentId, Sequence[Any]]:
        """The ``data_type`` records of one raw day file, in time order, by the
        instrument they belong to."""
        (instrument,) = instruments.values()
        return {instrument.id: list(self.parse(path, data_type, instrument))}
