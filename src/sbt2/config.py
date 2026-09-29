from dataclasses import dataclass
from pathlib import Path

ROOT = Path("data")
SOURCES = Path("config/sources.toml")
VENUE_PROFILES = Path("config/venues.toml")


@dataclass(frozen=True)
class Root:
    """The folder holding raw files, the catalog and results."""

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
