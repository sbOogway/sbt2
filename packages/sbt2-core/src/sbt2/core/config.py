from dataclasses import dataclass
from pathlib import Path

ROOT = Path("data")
VENUE_PROFILES = Path("config/venues.toml")


@dataclass(frozen=True)
class Root:
    """The folder holding raw files, the catalog, results and the known gaps."""

    path: Path = ROOT

    @property
    def raw(self) -> Path:
        return self.path / "raw"

    @property
    def catalog(self) -> Path:
        return self.path / "catalog"

    @property
    def results(self) -> Path:
        return self.path / "results"

    @property
    def known_gaps(self) -> Path:
        """The days each source confirmed it lacks, as a list per source."""
        return self.path / "known_gaps.toml"
