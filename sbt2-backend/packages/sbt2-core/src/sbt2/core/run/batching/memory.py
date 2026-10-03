import os
from dataclasses import dataclass

GiB = 2**30


def _half_the_memory() -> int:
    return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // 2


@dataclass(frozen=True)
class Memory:
    """Bytes for a whole batch, and the cap of each of its runs.

    Without a budget, a batch takes half the machine's memory, and at least a run's.
    """

    budget: int | None = None
    per_run: int = 4 * GiB

    def __post_init__(self) -> None:
        if self.budget is not None and self.budget < self.per_run:
            raise ValueError(
                f"a memory budget of {formatted_size(self.budget)} is below the "
                f"{formatted_size(self.per_run)} each run gets"
            )

    @property
    def concurrency(self) -> int:
        budget = self.budget or max(_half_the_memory(), self.per_run)
        return budget // self.per_run


def formatted_size(size: int) -> str:
    """Bytes in the largest binary unit that divides them, as systemd writes it."""
    for unit, power in (("T", 40), ("G", 30), ("M", 20), ("K", 10)):
        if size % 2**power == 0:
            return f"{size // 2**power}{unit}"
    return f"{size} bytes"
