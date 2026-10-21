from dataclasses import dataclass


@dataclass(frozen=True)
class Carry:
    """A non-trade cost or income, settled natively by the venue."""

    data_types: tuple[type, ...]
