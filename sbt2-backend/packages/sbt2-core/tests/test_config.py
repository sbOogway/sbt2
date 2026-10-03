from pathlib import Path

import pytest

from sbt2.core.config import ConfigFolder, Root


@pytest.mark.unit
def test_the_known_gaps_live_in_the_data_root() -> None:
    assert Root(Path("/d")).known_gaps == Path("/d/known_gaps.toml")


@pytest.mark.unit
def test_the_venue_profiles_live_in_the_config_folder() -> None:
    assert ConfigFolder(Path("/c")).venues == Path("/c/venues.toml")
