from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Self

from nautilus_trader.model import InstrumentId

_SUFFIX = "-OPTIONS"


@dataclass(frozen=True)
class ChainBand:
    """What bounds the contracts a chain run loads: the days to expiry from
    ``min_dte`` to ``max_dte``, and the strike within ``strike_band`` of the index,
    as a fraction of it."""

    min_dte: int = 0
    max_dte: int = 90
    strike_band: Decimal = Decimal("0.5")

    def __post_init__(self) -> None:
        if not all(isinstance(each, int) for each in (self.min_dte, self.max_dte)):
            raise ValueError("the days to expiry are whole numbers")
        if not 0 <= self.min_dte <= self.max_dte:
            raise ValueError("the days to expiry run from 0 up, the minimum first")
        if self.strike_band <= 0:
            raise ValueError("the strike band is above 0")

    @classmethod
    def from_table(cls, table: Mapping[str, Any]) -> Self:
        """The band a spec's ``chain`` table sets, with a default for each bound it
        leaves out; ``ValueError`` when the table is invalid."""
        try:
            values: dict[str, Any] = dict(table)
            if "strike_band" in values:
                values["strike_band"] = Decimal(str(values["strike_band"]))
            return cls(**values)
        except (TypeError, ArithmeticError, ValueError) as error:
            raise ValueError(f"the chain setting is invalid: {error}") from error

    def to_table(self) -> dict[str, Any]:
        return {
            "min_dte": self.min_dte,
            "max_dte": self.max_dte,
            "strike_band": f"{self.strike_band:f}",
        }


def is_chain(instrument_id: InstrumentId) -> bool:
    """Whether the id names the options of an underlying as a whole, such as
    ``BTC-OPTIONS.DERIBIT``."""
    return instrument_id.symbol.value.endswith(_SUFFIX)
