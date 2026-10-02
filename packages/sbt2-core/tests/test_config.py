from pathlib import Path

import pytest

from sbt2.core.config import Root


@pytest.mark.unit
def test_the_known_gaps_live_in_the_data_root() -> None:
    assert Root(Path("/d")).known_gaps == Path("/d/known_gaps.toml")
